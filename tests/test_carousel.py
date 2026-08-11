"""Carousel tests — the anchor chain, FR-105's ordering, and honest partial decks.

No network and no money: `submit` is a fake matching the pinned protocol `generate.carousel.Submit`,
the vision check rides a fake `models.StructuredCall`, and the packager's download is monkeypatched
so real `AssetFolder` files and a real `meta.yaml` still land on disk. `Env` is a local duck-typed
stub on purpose — the real `generate.Env` grows fields mid-wave and these tests must not care.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hypesocials.analyze import BriefBook
from hypesocials.config import Config
from hypesocials.generate.carousel import render_carousel
from hypesocials.models import (
    AssetRecord,
    AssetStatus,
    CopySet,
    LayoutZone,
    ParsedResult,
    PlanEntry,
    PlanEntryStatus,
    RenderFailCause,
    RenderOutcome,
    RenderOutcomeKind,
    RenderPriority,
    StyleBrief,
    TrendItem,
    VisionCheckResult,
)
from hypesocials.outputs import AssetFolder, PackagingError
from hypesocials.outputs import packager
from hypesocials.prompts_engine import PromptEngine, style_dna
from hypesocials.render import KieOutOfCredits
from hypesocials.sources import brief_key

TREND_REFS = ["https://cdn.virlo/p1.webp", "https://cdn.virlo/p2.webp", "https://cdn.virlo/p3.webp"]
_SLIDE_NO = re.compile(r"slide (\d+)")


# --------------------------------------------------------------------------------- fake seams


@dataclass(slots=True)
class Call:
    """One recorded `submit` call — everything a money/ordering assertion needs."""

    index: int
    slide: int
    job: str
    priority: RenderPriority
    kind: str
    label: str
    prompt: str
    image_urls: list[str]

    @property
    def url(self) -> str:
        return f"https://kie.test/slide-{self.slide}-{self.index}.jpg"


class FakeSubmit:
    """T4.3's metered submission door, faked: records every call and answers from a rule."""

    def __init__(self, rule: Any = None, events: list[str] | None = None) -> None:
        self.rule = rule
        self.calls: list[Call] = []
        self.events = events if events is not None else []

    async def __call__(self, entry, params, refs, *, job, priority, kind, label):
        match = _SLIDE_NO.search(label)
        call = Call(index=len(self.calls), slide=int(match.group(1)) if match else 0, job=job,
                    priority=priority, kind=kind, label=label, prompt=params.prompt,
                    image_urls=list(refs.image_urls))
        self.calls.append(call)
        self.events.append(f"submit:{call.slide}:{kind}")
        answer = self.rule(call) if self.rule is not None else ok(call)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def slide(self, number: int) -> Call:
        return next(call for call in self.calls if call.slide == number)


def ok(call: Call, cost: float = 0.03) -> RenderOutcome:
    return RenderOutcome(kind=RenderOutcomeKind.SUCCESS, task_id=f"kie_{call.index}",
                         request_token=f"tok_{call.index}", result_urls=[call.url], cost_usd=cost,
                         submitted_at=f"2026-08-09T10:0{call.index}:00Z",
                         completed_at=f"2026-08-09T10:1{call.index}:00Z")


def failed(cause: RenderFailCause = RenderFailCause.PROVIDER_FAIL, cost: float = 0.03
           ) -> RenderOutcome:
    return RenderOutcome(kind=RenderOutcomeKind.FAIL, task_id="kie_fail", fail_cause=cause,
                         fail_message="provider said no", cost_usd=cost)


class VisionStub:
    """A `models.StructuredCall` that answers the vision check from a per-call flag table."""

    def __init__(self, flags: list[set[int]] | None = None,
                 events: list[str] | None = None) -> None:
        self.flags = flags or []
        self.calls: list[int] = []
        self.events = events if events is not None else []

    async def __call__(self, role, messages, json_schema, images=None) -> ParsedResult:
        count = len(images or [])
        self.calls.append(count)
        self.events.append(f"check:{count}")
        flagged = self.flags[len(self.calls) - 1] if len(self.calls) <= len(self.flags) else set()
        return ParsedResult(parsed={"verdicts": [
            {"image": i, "text_broken": i in flagged, "fake_ui": False, "detail": "garbled"}
            for i in range(1, count + 1)]}, raw_text="{}")


class Log:
    """`outputs.LogWriter`'s three call shapes, remembering only what tests assert on."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def event(self, event_type: str, message: str = "", **data: Any) -> str:
        self.records.append((event_type, message))
        return f"ev_{len(self.records):04d}"

    warn = event
    error = event

    def types(self) -> list[str]:
        return [event_type for event_type, _ in self.records]


@dataclass
class Env:
    """Duck-typed stand-in for `generate.Env` — exactly the fields carousel.py reads."""

    config: Config
    run_dir: Path
    engine: PromptEngine
    log: Log
    trends: dict[str, TrendItem] = field(default_factory=dict)
    style_briefs: dict[str, StyleBrief] = field(default_factory=dict)
    copy: dict[str, CopySet] = field(default_factory=dict)
    local_refs: dict[str, list[Path]] = field(default_factory=dict)
    niche_descriptor: str = "Audience: founders · Vibe: blunt"
    llm_call: Any = None
    halted: bool = False
    credits_exhausted: bool = False
    disk_full: bool = False  # 10 §10 — T4.3 carries the same field on the real Env

    def brief_for(self, entry: PlanEntry) -> StyleBrief | None:
        """Mirrors `generate.Env.brief_for` (FR-9/12, amended 2026-08-11).

        Delegates to the real resolver rather than reimplementing the key, so this stub cannot
        drift from the production lookup — the whole point of the pair key is that exactly one
        place decides which group a creative belongs to.
        """
        key = entry.trend_key or ""
        return self.style_briefs.get(
            brief_key(key, self.trends.get(key), entry.trend_reuse_index))


# ------------------------------------------------------------------------------------ fixtures


@pytest.fixture(autouse=True)
def downloads(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Every `store_render` writes real bytes to a real folder; nothing touches the network."""
    control = SimpleNamespace(fetched=[], fail_contains="", fail_reason="download_failed")

    async def _download(url: str) -> bytes:
        control.fetched.append(url)
        if control.fail_contains and control.fail_contains in url:
            raise PackagingError(f"download failed: {control.fail_reason}",
                                 reason=control.fail_reason)
        return b"\xff\xd8fake-jpeg-bytes"

    monkeypatch.setattr(packager, "_download", _download)
    return control


def make_entry(slides: int = 4, **overrides: Any) -> PlanEntry:
    entry = PlanEntry(order=0, asset_id="0001_carousel_linkedin", creative_format="carousel",
                      platform="linkedin", language="en", aspect_ratio="1:1", variant="analyzed",
                      trend_key="t1", slide_count=slides, estimated_cost_usd=0.15)
    for key, value in overrides.items():
        setattr(entry, key, value)
    return entry


def make_env(tmp_path: Path, entry: PlanEntry, *, texts: list[str] | None = None,
             brief: bool = True, **overrides: Any) -> Env:
    config = Config()
    trend = TrendItem(history_key="t1", monitor_id="m1", name="AI tool stacks",
                      why_it_works="numbers in the first line", is_slideshow=True,
                      hook_texts=["Nobody tells you this about AI tools"],
                      panel_texts=["panel one", "panel two"],
                      reference_groups=[list(TREND_REFS)])
    style = StyleBrief(trend_key="t1", render_prompt="Flat graphic card, centred subject.",
                       palette=["#1B1F3B", "#F4C95D"], typography="bold condensed sans",
                       layout_zones=[LayoutZone("upper third", "headline", "bold, sentence case")],
                       exclusions=["usernames", "engagement counters"],
                       text_placement="headline upper third", image_treatment="flat graphic",
                       visual_pacing="one idea per panel", hook_pattern="negative-outcome claim")
    copyset = CopySet(asset_id=entry.asset_id, language="en", trend_key="t1",
                      caption="Most people wire this backwards.", hashtags=["#ai"],
                      headline="Wired backwards", narrative_arc="hook, escalation, payoff, close",
                      slide_texts=texts if texts is not None
                      else ["Wired backwards", "Two", "Three", "Four"])
    # 2026-08-11 (A4): briefs are keyed by the (trend, reference group) PAIR, not by the trend —
    # `analyze.style_briefs()` returns a `BriefBook` keyed `"<trend_key>#<group index>"`. The book
    # still answers a bare trend key, which is what `carousel.py` looks up, so this fixture is the
    # production shape rather than a compatibility shim.
    env = Env(config=config, run_dir=tmp_path, engine=PromptEngine(), log=Log(),
              trends={"t1": trend}, style_briefs=BriefBook({"t1#0": style}) if brief else BriefBook(),
              copy={entry.asset_id: copyset})
    for key, value in overrides.items():
        setattr(env, key, value)
    return env


def make_folder(tmp_path: Path, entry: PlanEntry) -> AssetFolder:
    return AssetFolder(tmp_path, AssetRecord(
        asset_id=entry.asset_id, source="t1", source_name="AI tool stacks",
        platform=entry.platform, creative_format="carousel", variant=entry.variant,
        aspect_ratio_requested=entry.aspect_ratio, slide_count=entry.slide_count))


def dna_block(prompt: str) -> str:
    """The STYLE_DNA segment of one assembled slide prompt — FR-189's unit of comparison."""
    return prompt.split("STYLE_DNA", 1)[1].split("SLIDE CONTENT", 1)[0]


# --------------------------------------------------------------- FR-105 ordering (barrier item)


async def test_fr105_anchor_checked_before_slides_submitted(tmp_path: Path) -> None:
    """The anchor is a chained artifact: checking it after the deck is checking it N renders too
    late (FR-95/105). Slide 1 renders alone, is checked, and only then do slides 2–N go out."""
    entry, events = make_entry(slides=4), []
    env = make_env(tmp_path, entry)
    env.config.run.vision_check = True
    env.llm_call = VisionStub(events=events)
    submit = FakeSubmit(events=events)

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    anchor_check = events.index("check:1")
    assert events[0] == "submit:1:projected", "slide 1 renders first and alone (FR-95)"
    assert events[1] == "check:1", "nothing else is ordered before the anchor verdict"
    later = [index for index, name in enumerate(events) if name.startswith("submit:")
             and not name.startswith("submit:1:")]
    assert later and min(later) > anchor_check, "no slide 2–N is submitted before the check"
    assert env.llm_call.calls == [1, 4], "one anchor call, then ONE call for the whole deck"
    assert record.status is AssetStatus.SUCCESS
    assert record.vision_check_result is VisionCheckResult.PASSED


async def test_deck_check_is_one_call_carrying_every_delivered_slide(tmp_path: Path) -> None:
    """N slides never cost N calls, and the estimate prices it the same way (FR-105/107)."""
    entry = make_entry(slides=5)
    env = make_env(tmp_path, entry, texts=["a", "b", "c", "d", "e"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    assert env.llm_call.calls == [1, 5]


async def test_vision_check_off_never_calls_the_model(tmp_path: Path) -> None:
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.llm_call = VisionStub()  # present, but `run.vision_check` is off

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    assert env.llm_call.calls == []
    assert record.vision_check_result is VisionCheckResult.NOT_CHECKED


# ------------------------------------------------------- FR-95 anchor failure (barrier item)


async def test_anchor_failure_falls_back_to_independent_slides_precommitted(
    tmp_path: Path,
) -> None:
    """Slide 1 failing degrades the deck to independent generation — and that fallback is
    PRE-COMMITTED work, never discretionary: the cap may not split a deck (FR-95/FR-106b)."""
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry)
    submit = FakeSubmit(rule=lambda call: failed() if call.index == 0 else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert len(submit.calls) == 5, "the failed anchor plus N independent slides (FR-107's N+1)"
    fallback = submit.calls[1:]
    assert [call.slide for call in fallback] == [1, 2, 3, 4]
    assert {call.kind for call in fallback} == {"precommitted"}, "never discretionary"
    assert {call.priority for call in fallback} == {RenderPriority.WAVE2}
    assert all(call.image_urls == TREND_REFS for call in fallback), "no anchor reference"
    assert "carousel_anchor_fallback" in env.log.types()
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 4


async def test_slides_two_onward_lead_with_the_finished_anchor(tmp_path: Path) -> None:
    """FR-95: the finished slide 1 is the PRIMARY reference, ahead of the trend references."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"])
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    anchor = submit.slide(1)
    assert anchor.kind == "projected" and anchor.priority is RenderPriority.WAVE1
    assert anchor.image_urls == TREND_REFS
    for number in (2, 3):
        call = submit.slide(number)
        assert call.image_urls[0] == anchor.url, "the anchor leads the reference set"
        assert call.image_urls[1:] == TREND_REFS, "the FR-91 trend set follows it"
        assert "ANCHOR REFERENCE" in call.prompt, "the template-lock block is prepended"
        assert call.kind == "precommitted" and call.priority is RenderPriority.WAVE2


# ------------------------------------------------------------------------------ FR-189 style DNA


async def test_style_dna_byte_identical_across_slides(tmp_path: Path) -> None:
    """FR-189 — the style-DNA block is built ONCE per deck and repeated verbatim; only the slide
    content and the slide index change. Drift prevention is templating, not a QA loop (FR-20)."""
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry)
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    blocks = [dna_block(call.prompt) for call in submit.calls]
    assert len(blocks) == 4
    assert len(set(blocks)) == 1, "byte-identical on every slide"
    expected = style_dna(env.style_briefs["t1#0"])  # 2026-08-11: pair-keyed (A4)
    assert expected and expected in blocks[0]
    indexes = [re.search(r"slide (\d+ of \d+)", call.prompt).group(1) for call in submit.calls]
    assert indexes == ["1 of 4", "2 of 4", "3 of 4", "4 of 4"], "only the index moves"


async def test_deck_size_is_the_config_ceiling_reduced_by_the_copy(tmp_path: Path) -> None:
    """FR-95/257: config is the ceiling; the trend's own pacing may only reduce it."""
    entry = make_entry(slides=5)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"])
    short = FakeSubmit()
    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=short)
    assert [call.slide for call in short.calls] == [1, 2, 3]

    entry2 = make_entry(slides=3, asset_id="0002_carousel_linkedin")
    env2 = make_env(tmp_path, entry2, texts=[f"line {n}" for n in range(8)])
    long = FakeSubmit()
    await render_carousel(entry2, env2, make_folder(tmp_path, entry2), submit=long)
    assert [call.slide for call in long.calls] == [1, 2, 3], "the ceiling is never raised"


# ------------------------------------------------------------------- partial decks & moderation


async def test_a_failed_slide_download_ships_an_incomplete_deck(
    tmp_path: Path, downloads: SimpleNamespace
) -> None:
    """10 §10: completed slides ship, metadata records `incomplete` with the missing numbers.
    Explicitly NOT all-or-nothing (D3)."""
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry)
    downloads.fail_contains = "slide-3-"
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    assert record.status is AssetStatus.SUCCESS, "a labelled incomplete deck beats nothing"
    assert record.missing_slide_numbers == [3]
    assert record.slide_count == 3
    assert "incomplete" in [tag.value for tag in record.degradations]
    on_disk = sorted(path.name for path in folder.path.glob("slide_*.jpg"))
    assert on_disk == ["slide_01.jpg", "slide_02.jpg", "slide_04.jpg"]
    assert packager.read_meta(folder.path)["missing_slide_numbers"] == [3]


async def test_an_incomplete_deck_carries_the_run_to_exit_one(
    tmp_path: Path, downloads: SimpleNamespace
) -> None:
    """The 2026-08-11 regression, end to end: the deck the carousel really packages must reach
    FR-202's code 1 through the tag it really writes.

    `output/20260811_233910_wikf` delivered 6/6 creatives and exited **0** ("everything planned was
    delivered") while `Li_car_ai-trends-tracker_analyzed_05/meta.yaml` said `status: success`,
    `slide_count: 4`, `missing_slide_numbers: [2]`, `degradations: ['text_trimmed', 'incomplete']`
    — slide 2 lost to "timeout — no terminal state within 180s". FR-202: "a delivered carousel
    shipped incomplete … a lost slide is a loss even when the deck ships".

    The entry deliberately carries **no `skip_reason`** — the deck shipped, so `package()` marks the
    folder instead — which is precisely why `decide_exit_code` has to read the degradation tags.
    """
    from hypesocials.runner import EXIT_OK, EXIT_PARTIAL, decide_exit_code

    entry = make_entry(slides=5)  # the live deck: five planned, four delivered, slide 2 timed out
    env = make_env(tmp_path, entry, texts=[f"line {n}" for n in range(5)])
    downloads.fail_contains = "slide-2-"

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    assert record.status is AssetStatus.SUCCESS and record.slide_count == 4
    assert record.missing_slide_numbers == [2]
    assert entry.status is PlanEntryStatus.SUCCESS and entry.skip_reason is None
    degradations = {record.asset_id: record.degradations}  # the map `runner._package` builds
    assert decide_exit_code([entry]) == EXIT_OK, "the pre-fix answer, blind to the tags"
    assert decide_exit_code([entry], degradations=degradations) == EXIT_PARTIAL


async def test_a_deck_that_delivers_nothing_keeps_its_paid_artifacts(tmp_path: Path) -> None:
    """FR-74: the copy was paid for, so the folder, the caption and a failed meta all survive."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    folder = make_folder(tmp_path, entry)
    folder.write_caption("Most people wire this backwards.", ["#ai"])

    record = await render_carousel(entry, env, folder, submit=FakeSubmit(rule=lambda c: failed()))

    assert record.status is AssetStatus.FAILED and entry.status is PlanEntryStatus.FAILED
    assert record.missing_slide_numbers == [1, 2, 3] and record.slide_count == 0
    assert (folder.path / "caption.txt").is_file()
    assert (folder.path / "SKIP_REASON.txt").read_text(encoding="utf-8").strip()
    assert record.actual_cost_usd > 0, "spend tallies on submission, failures included (FR-106)"


async def test_moderation_refusal_retries_reference_free_as_discretionary(
    tmp_path: Path,
) -> None:
    """FR-97: one resubmission with every reference removed, marked `refs_dropped_moderation`."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    refused: set[int] = set()

    def rule(call: Call) -> RenderOutcome:
        if call.slide == 2 and call.slide not in refused:
            refused.add(call.slide)
            return failed(RenderFailCause.MODERATION)
        return ok(call)

    submit = FakeSubmit(rule=rule)
    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    retry = next(call for call in submit.calls if call.kind == "discretionary")
    assert retry.slide == 2 and retry.image_urls == [], "every reference removed (FR-97)"
    assert retry.job == "slide" and retry.priority is RenderPriority.WAVE2
    assert "refs_dropped_moderation" in [tag.value for tag in record.degradations]
    assert record.slide_count == 3, "the deck is whole; only the references were dropped"
    assert "moderation_retry" in env.log.types()


async def test_halt_before_the_deck_orders_nothing_and_packages_honestly(
    tmp_path: Path,
) -> None:
    """FR-201/108: Ctrl+C and the deadline stop ORDERING; nothing was bought for this deck."""
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry, halted=True)
    submit = FakeSubmit()
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=submit)

    assert submit.calls == [], "not one slide was ordered"
    assert record.status is AssetStatus.FAILED
    assert entry.status is PlanEntryStatus.ABANDONED
    assert "abandoned" in [tag.value for tag in record.degradations]
    assert "interrupted" in (record.skip_reason or "")
    assert record.actual_cost_usd == 0.0


async def test_halt_after_the_anchor_ships_the_slides_that_exist(tmp_path: Path) -> None:
    """A halt mid-deck stops ordering and packages what already landed (FR-201)."""
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry)

    def rule(call: Call) -> RenderOutcome:
        env.halted = True  # the operator hits Ctrl+C while slide 1 is in flight
        return ok(call)

    submit = FakeSubmit(rule=rule)
    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call.slide for call in submit.calls] == [1]
    assert record.slide_count == 1 and record.missing_slide_numbers == [2, 3, 4]
    assert "incomplete" in [tag.value for tag in record.degradations]


async def test_out_of_credits_packages_the_deck_instead_of_raising(tmp_path: Path) -> None:
    """FR-167: the 402 is a whole-run condition — latched once, never re-tried per slide."""
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry)

    def rule(call: Call) -> Any:
        return ok(call) if call.slide == 1 else KieOutOfCredits("HTTP 402")

    record = await render_carousel(entry, env, make_folder(tmp_path, entry),
                                   submit=FakeSubmit(rule=rule))

    assert env.credits_exhausted is True
    assert record.slide_count == 1 and record.missing_slide_numbers == [2, 3, 4]
    assert record.status is AssetStatus.SUCCESS


# --------------------------------------------------------------------- FR-105 retries & verdicts


async def test_flagged_anchor_with_a_declined_retry_ships_and_records_retried_failed(
    tmp_path: Path,
) -> None:
    """A flagged anchor whose discretionary re-render the cap declines still anchors the deck —
    one retry is the cap everywhere — but the verdict stays honest (FR-95/FR-106c/FR-27)."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[{1}])  # anchor flagged; the deck call comes back clean
    submit = FakeSubmit(rule=lambda call: None if call.kind == "discretionary" else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    declined = [call for call in submit.calls if call.kind == "discretionary"]
    assert len(declined) == 1 and declined[0].slide == 1, "exactly one re-render was attempted"
    assert record.slide_count == 3, "the flagged anchor ships and the deck is built on it"
    assert record.vision_check_result is VisionCheckResult.RETRIED_FAILED


async def test_a_flagged_anchor_re_render_replaces_slide_one_with_shorter_text(
    tmp_path: Path,
) -> None:
    """FR-105's retry changes the INPUT: less text, a tighter stated budget, larger type."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry,
                   texts=["A slide-one line that is far longer than the retry budget", "b", "c"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[{1}])
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    first, retry = submit.calls[0], submit.calls[1]
    assert retry.slide == 1 and retry.kind == "discretionary"
    assert retry.priority is RenderPriority.WAVE1, "the deck is still waiting on this anchor"
    assert len(retry.prompt) < len(first.prompt) or "re-render" in retry.prompt
    assert "re-render of an image whose text came back broken" in retry.prompt
    assert submit.calls[2].image_urls[0] == retry.url, "the deck anchors to the FINAL slide 1"
    assert env.llm_call.calls == [1, 1, 3], "check, re-render, RE-CHECK, then the deck call"
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED


async def test_a_successful_re_render_is_re_checked_before_it_earns_retried_passed(
    tmp_path: Path,
) -> None:
    """FR-27's `retried_passed` is only honest when a real second verdict says so, and the
    estimator already prices the vision-retry allowance as render PLUS re-check."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[{1}])  # anchor flagged once; every later call comes back clean
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert env.llm_call.calls == [1, 1, 3], "the re-rendered anchor is re-checked, once"
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED
    assert len([call for call in submit.calls if call.kind == "discretionary"]) == 1


async def test_re_renders_are_re_checked_in_one_batched_call(tmp_path: Path) -> None:
    """FR-105 call economics hold for the re-check too: two re-rendered slides, ONE further call.
    The slide whose re-render still comes back flagged stays `retried_failed` (FR-27 honesty)."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.vision_check = True
    # anchor clean · deck flags slides 2 and 3 · the re-check flags the FIRST re-rendered slide
    env.llm_call = VisionStub(flags=[set(), {2, 3}, {1}])
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert env.llm_call.calls == [1, 3, 2], "one re-check carrying both re-rendered slides"
    assert [call.slide for call in submit.calls if call.kind == "discretionary"] == [2, 3]
    assert record.vision_check_result is VisionCheckResult.RETRIED_FAILED, "slide 2 still broken"
    assert record.slide_count == 3, "a flagged slide still ships — one retry, then it goes (D3)"


async def test_a_flagged_slide_in_the_deck_check_gets_one_discretionary_re_render(
    tmp_path: Path,
) -> None:
    """Each flagged slide earns at most one re-render, and it is discretionary spend (FR-106c)."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[set(), {3}])  # anchor clean, slide 3 flagged post-deck
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    retries = [call for call in submit.calls if call.kind == "discretionary"]
    assert [call.slide for call in retries] == [3]
    assert retries[0].image_urls[0] == submit.calls[0].url, "still template-locked to the anchor"
    assert env.llm_call.calls == [1, 3, 1], "anchor call, deck call, one re-check of the re-render"
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED


async def test_disk_full_stops_further_downloads_and_flags_the_run(
    tmp_path: Path, downloads: SimpleNamespace
) -> None:
    """10 §10: that creative fails with `disk_full` and further downloads STOP rather than
    thrash a full disk — the condition outlives this deck, so the run carries it."""
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry)
    downloads.fail_contains, downloads.fail_reason = "slide-2-", "disk_full"
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    assert env.disk_full is True, "the runner needs this beyond the one creative"
    assert [url for url in downloads.fetched if "slide-3-" in url or "slide-4-" in url] == []
    assert record.slide_count == 1 and record.missing_slide_numbers == [2, 3, 4]
    assert sorted(path.name for path in folder.path.glob("slide_*.jpg")) == ["slide_01.jpg"]
    assert "disk_full" in " ".join(message for _, message in env.log.records)
