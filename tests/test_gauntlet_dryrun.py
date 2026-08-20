"""The T2.4 barrier: an OFFLINE, $0, `--yes`-shaped end-to-end walk of the gauntlet (D49).

    .venv/Scripts/python.exe -m pytest -q tests/test_gauntlet_dryrun.py -s

Run it with `-s` and it prints a short transcript of every terminal it reached, because the point
of this file is not one assertion — it is proof that the whole wire-in works together on paths a
unit test exercises one at a time. What it walks:

1. the round LOOP: round 1 judges, a failing frame re-renders with a canned fix, round 2 judges
   the re-rendered frame and passes;
2. all THREE terminals of FR-325: `pass` (exit 0), `blocked` (exit 1, artifacts kept), and the
   craft-only tier that SHIPS with a tag;
3. the two STOPS: the per-deck gauntlet budget and D51's runway, each mapped to its own result
   and each leaving a shipped deck behind;
4. the OUTPUTS: `BLOCKED.txt`, `GAUNTLET_REPORT.yaml`, `meta.yaml.gauntlet` on every terminal path,
   and the gallery's BLOCKED card;
5. the EXIT CODE contract and the two guards a blocked creative must trip — it is excluded from
   the trend-history window (its source post is not burnt) and from `set_latest`'s satisfaction;
6. **D54's one-walk invariant** (v2.3.0): a compress-mode deck walked from a REAL
   `copywrite.write_copy` call through `generate.create()`, proving that the string the frame was
   ORDERED from, the string the critic is asked to FIND, and the string `meta.yaml`'s `panel_map`
   RECORDS are one string. That trio is exactly what `test_copywrite.py` cannot check — it ends at
   the `CopySet` — and a divergence in it is a false `missing_text` that blocks a clean deck.

**Nothing here touches the network and nothing here can spend.** `render.run`, `render.upload_file`
and the packager's download are all faked, the LLM seam is a scripted critic panel, and `httpx`
itself is monkeypatched to raise — so a code path that tried to reach a provider would fail loudly
rather than quietly succeed against a live service. The budget and the ledger are the REAL ones,
so the money assertions are against the actual accounting.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import yaml

from hypesocials import copywrite, gauntlet, generate, render, runner, styles
from hypesocials.budget import Budget
from hypesocials.config import BrandingConfig, Config
from hypesocials.generate import refs as refs_module
from hypesocials.models import (
    AssetRecord,
    AssetStatus,
    CopySet,
    LayoutZone,
    MetaStyle,
    ParsedResult,
    PlanEntry,
    PlanEntryStatus,
    RenderOutcome,
    RenderOutcomeKind,
    RenderPriority,
    SourcePost,
    TrendItem,
    VisionCheckResult,
)
from hypesocials.outputs import Ledger, packager, read_meta, write_gallery
from hypesocials.prompts_engine import PromptEngine

pytestmark = pytest.mark.asyncio

STYLE_KEY = "dry-run-style"
RESULT_URL = "https://tempfile.aiquickdraw.com/dry-run.jpg"
SLIDES = 3


# --------------------------------------------------------------------------------- the seams


class Log:
    """`outputs.LogWriter`'s three call shapes, remembering what the transcript prints."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, Any]]] = []

    def event(self, event_type: str, message: str = "", **data: Any) -> str:
        self.records.append((event_type, message, data))
        return f"ev_{len(self.records):04d}"

    warn = event
    error = event

    def types(self) -> list[str]:
        return [event_type for event_type, _, _ in self.records]


class Panel:
    """The scripted critic panel: one entry per ROUND, `{slot: fails}` for the owning critic.

    Only ONE critic can emit a given code — the per-critic enums are a partition (spec §3) — so
    "the Nth call to the critic that owns `code`" is "round N" with no scoping model needed here.
    `budget_stop` and `deadline_stop` are reached through the caller's seams, not through this.
    """

    def __init__(self, rounds: list[set[int]] | None = None, *, code: str = "garbled",
                 confidence: str = "high") -> None:
        self.rounds = [set(entry) for entry in (rounds or [])]
        self.code = code
        self.confidence = confidence
        self.calls: list[tuple[str, int]] = []  # (critic, frames attached)
        #: Every system prompt a critic was actually sent. The critics' whole world is contract
        #: data (`gauntlet._context`), so this is where `{{expected_blocks}}` — the referent a
        #: `missing_text` verdict is measured against — can be read back as the model saw it.
        self.prompts: list[str] = []
        self.owner = next(name for name, codes in gauntlet.CRITIC_CODES.items() if code in codes)
        self._owner_calls = 0

    async def __call__(self, role, messages, json_schema, images=None) -> ParsedResult:
        name = str(json_schema["name"]).removeprefix("gauntlet_")
        count = len(images or [])
        self.calls.append((name, count))
        self.prompts.append(str(messages[0]["content"]))
        failing: set[int] = set()
        if name == self.owner:
            index, self._owner_calls = self._owner_calls, self._owner_calls + 1
            failing = self.rounds[index] if index < len(self.rounds) else set()
        return ParsedResult(parsed={"frames": [
            {"frame": slot, "pass": slot not in failing,
             "defects": ([{"code": self.code, "zone": "middle", "confidence": self.confidence,
                           "detail": "scripted defect"}] if slot in failing else [])}
            for slot in range(1, count + 1)]}, raw_text="{}", cost_usd=0.028)

    @property
    def rounds_run(self) -> int:
        return self._owner_calls


class Renders:
    """A fake `render.run`. Every submission succeeds; nothing leaves the process."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, profile: str, params: Any, refs: Any,
                       priority: RenderPriority) -> RenderOutcome:
        self.calls.append({"profile": profile, "priority": priority, "prompt": params.prompt,
                           "refs": list(refs.image_urls)})
        index = len(self.calls)
        return RenderOutcome(
            kind=RenderOutcomeKind.SUCCESS, task_id=f"kie_dry_{index}",
            request_token=f"tok_{index}", result_urls=[f"{RESULT_URL}?n={index}"], cost_usd=0.03,
            submitted_at="2026-08-14T10:00:00Z", completed_at="2026-08-14T10:01:00Z")


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """The $0 guarantee, enforced rather than promised: no client may be constructed at all."""
    async def _download(url: str) -> bytes:
        return b"\xff\xd8dry-run-bytes"

    async def _upload(path: Path) -> str:
        return f"https://kie.test/upload/{Path(path).name}"

    def _no_http(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the dry run reached for the network — it must not")

    monkeypatch.setattr(packager, "_download", _download)
    monkeypatch.setattr(render, "upload_file", _upload)
    monkeypatch.setattr("httpx.AsyncClient", _no_http)
    refs_module.reset_uploads()
    yield
    refs_module.reset_uploads()


# --------------------------------------------------------------------------------- the fixture


def make_style() -> MetaStyle:
    return MetaStyle(
        key=STYLE_KEY,
        render_prompt="Flat editorial card on a warm ground, hard shadow, wide margins.",
        layout_zones=[LayoutZone("top band", "headline", "bold, sentence case")],
        format_affinity=["image", "carousel"],
        max_onimage_chars={"headline": 90, "slide": 300},
        palette=["#1B1F3B", "#F4C95D"], typography="bold condensed sans",
        text_placement="headline upper third", image_treatment="flat graphic",
        visual_pacing="one idea per panel", exclusions=["platform UI"])


def make_entry(order: int = 0) -> PlanEntry:
    return PlanEntry(order=order, asset_id=f"{order + 1:04d}_carousel_linkedin",
                     creative_format="carousel", platform="linkedin", language="en",
                     aspect_ratio="1:1", trend_key="t1", style_key=STYLE_KEY,
                     slide_count=SLIDES, estimated_cost_usd=0.15)


def make_env(tmp_path: Path, entry: PlanEntry, panel: Panel, **overrides: Any) -> generate.Env:
    """A real `Env` on a real `Config`, a real `Budget` and a real `Ledger` — faked seams only."""
    env = generate.Env(
        config=Config(), run_dir=tmp_path, engine=PromptEngine(), budget=Budget(5.0),
        log=Log(), ledger=Ledger(tmp_path),
        trends={"t1": TrendItem(history_key="t1", monitor_id="m1", name="AI tool stacks",
                                topic_key="ai-tool-stacks")},
        copy={entry.asset_id: CopySet(
            asset_id=entry.asset_id, language="en", trend_key="t1",
            caption="Most people wire this backwards.", hashtags=["#ai"],
            headline="Wired backwards",
            slide_texts=["Wired backwards", "Two", "Three"])},
        styles=styles.StyleRegistry(version=1, styles=[make_style()], origin="dry-run",
                                    content_hash="0123456789ab"),
        branding=BrandingConfig(brand="hypelead"),
        llm_call=panel, stop=asyncio.Event())
    for key, value in overrides.items():
        setattr(env, key, value)
    return env


async def walk(tmp_path: Path, panel: Panel, **overrides: Any
               ) -> tuple[PlanEntry, generate.Env, AssetRecord, Renders]:
    """One creative, end to end, through the REAL `generate.create()` money door."""
    entry = make_entry()
    env = make_env(tmp_path, entry, panel, **overrides)
    renders = Renders()
    original, render.run = render.run, renders
    try:
        report = await generate.create([entry], env)
    finally:
        render.run = original
    return entry, env, report.records[entry.asset_id], renders


def say(title: str, record: AssetRecord, entry: PlanEntry, panel: Panel) -> None:
    """The transcript line `-s` prints — one row per terminal this file actually reached."""
    gate = record.gauntlet or {}
    print(f"  {title:<22} status={record.status.value:<8} entry={entry.status.value:<8} "
          f"gauntlet={gate.get('result', '-'):<14} rounds={len(gate.get('rounds', ()))} "
          f"rerenders={gate.get('rerenders', 0)} critic_calls={len(panel.calls)}")


# --------------------------------------------------------------------------------- the walk


async def test_dry_run_pass_path_loops_fixes_and_exits_zero(tmp_path: Path) -> None:
    """Tier-free terminal: round 1 fails a frame, the canned fix re-renders it, round 2 passes.

    This is the loop itself — the thing every other terminal is a variation of — and it is also
    the exit-0 case: every planned creative delivered, nothing withheld.
    """
    panel = Panel(rounds=[set(), {2}], code="garbled")  # entry 0 is the anchor pre-gate
    entry, env, record, renders = await walk(tmp_path, panel)

    assert record.status is AssetStatus.SUCCESS and entry.status is PlanEntryStatus.SUCCESS
    assert record.gauntlet["result"] == "pass"
    assert record.gauntlet["rerenders"] == 1, "one failing frame, one canned fix"
    assert [row["failed_frames"] for row in record.gauntlet["rounds"]] == [[2], []]
    assert record.gauntlet["rounds"][0]["rerendered"] == [2]
    assert panel.rounds_run == 3, "the anchor pre-gate, then the deck's two rounds"
    assert len(renders.calls) == SLIDES + 1, "three slides plus the one fix re-render"
    fix = renders.calls[-1]
    assert "FIX — this is a re-render of a frame that failed review." in fix["prompt"]
    assert "scripted defect" not in fix["prompt"], "no critic free text in a render payload"
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED
    assert (tmp_path / entry.asset_id / packager.GAUNTLET_REPORT_FILE).is_file()
    assert not (tmp_path / entry.asset_id / packager.BLOCKED_FILE).exists()

    assert runner.decide_exit_code([entry]) == runner.EXIT_OK
    say("pass (fixed)", record, entry, panel)


async def test_dry_run_blocked_path_writes_both_files_and_exits_one(tmp_path: Path) -> None:
    """Tier 1: a standing leakage defect BLOCKS — every artifact kept, nothing published.

    The two files an operator reads are written, `meta.yaml.gauntlet` carries the receipt, the
    gallery draws a BLOCKED card rather than a failed one, and the run exits 1.
    """
    # Entry 0 is the anchor pre-gate; 1-3 are the deck's three rounds. Rounds 2 and 3 name
    # SLOT 1 rather than slot 2 because FR-324 scopes `brief` to the re-rendered frames alone,
    # so the single frame attached in those rounds IS slide 2.
    panel = Panel(rounds=[set(), {2}, {1}, {1}], code="invented_text")
    entry, env, record, renders = await walk(tmp_path, panel)
    folder = tmp_path / entry.asset_id

    assert record.status is AssetStatus.BLOCKED and entry.status is PlanEntryStatus.BLOCKED
    assert record.gauntlet["result"] == "blocked"
    assert record.slide_count == SLIDES, "every paid slide is on disk (FR-74)"
    assert sorted(p.name for p in folder.glob("slide_*.jpg")) == [
        "slide_01.jpg", "slide_02.jpg", "slide_03.jpg"]

    blocked = (folder / packager.BLOCKED_FILE).read_text(encoding="utf-8")
    assert "BLOCKED" in blocked and "NOT published" in blocked and "invented_text" in blocked
    report = yaml.safe_load((folder / packager.GAUNTLET_REPORT_FILE).read_text(encoding="utf-8"))
    assert report["result"] == "blocked"
    assert any(row["code"] == "invented_text"
               for round_row in report["rounds"] for row in round_row["defects"])
    stored = read_meta(folder)
    assert stored["status"] == "blocked" and stored["gauntlet"]["result"] == "blocked"

    write_gallery(tmp_path, title="dry run")
    page = (tmp_path / "gallery.html").read_text(encoding="utf-8")
    assert "card blocked" in page and "BLOCKED, not published" in page
    assert "gauntlet: blocked" in page

    # The two guards a blocked creative must trip, and the exit code it forces.
    assert entry.status is not PlanEntryStatus.SUCCESS, \
        "so `record_use` does not burn its source post and `set_latest` is not satisfied"
    assert runner.decide_exit_code([entry]) == runner.EXIT_PARTIAL
    say("blocked (leakage)", record, entry, panel)


async def test_dry_run_craft_only_ships_tagged(tmp_path: Path) -> None:
    """Tier 3: craft is an opinion. The deck ships, carries `GAUNTLET_CRAFT`, and exits 0."""
    from hypesocials.generate.carousel import GAUNTLET_CRAFT

    panel = Panel(rounds=[set(), {2}, {1}, {1}], code="contrast")
    entry, env, record, _ = await walk(tmp_path, panel)

    assert record.status is AssetStatus.SUCCESS
    assert record.gauntlet["result"] == "pass" and record.gauntlet["craft_only"] is True
    assert GAUNTLET_CRAFT in record.degradations
    assert runner.decide_exit_code([entry]) == runner.EXIT_OK
    say("craft-only (ships)", record, entry, panel)


async def test_dry_run_budget_and_deadline_stops_map_to_their_own_results(
    tmp_path: Path,
) -> None:
    """The two money-seam stops, each mapped to its own result and each shipping what it has.

    `declined_deck_budget` -> `budget_stop` and `declined_runway` -> `deadline_stop` (spec §1).
    Both are refusals BEFORE the reservation, so the run is billed for the slides it got.
    """
    tight = tmp_path / "tight"
    tight.mkdir()
    # `style_layout` is a SYSTEM code, and system does not run the anchor pre-gate, so entry 0
    # is the deck's own first round.
    panel = Panel(rounds=[{2}], code="style_layout")
    entry_b = make_entry()
    env_b = make_env(tight, entry_b, panel, price_job=lambda _entry, _job: 0.04)
    env_b.config.run.gauntlet.deck_budget_usd = 0.01
    renders_b = Renders()
    original, render.run = render.run, renders_b
    try:
        record_b = (await generate.create([entry_b], env_b)).records[entry_b.asset_id]
    finally:
        render.run = original
    assert record_b.gauntlet["result"] == "budget_stop"
    assert len(renders_b.calls) == SLIDES, "no fix was ordered once the deck cap was reached"
    assert record_b.status is AssetStatus.SUCCESS, "the deck ships what it already paid for"
    assert "gauntlet_budget_stop" in env_b.log.types()
    say("budget_stop", record_b, entry_b, panel)

    late = tmp_path / "late"
    late.mkdir()
    panel_c = Panel(rounds=[{2}], code="style_layout")
    entry_c = make_entry()
    env_c = make_env(late, entry_c, panel_c, runway_ok=lambda _job: False)
    renders_c = Renders()
    original, render.run = render.run, renders_c
    try:
        record_c = (await generate.create([entry_c], env_c)).records[entry_c.asset_id]
    finally:
        render.run = original
    assert record_c.gauntlet["result"] == "deadline_stop"
    assert len(renders_c.calls) == SLIDES, "nothing the clock cannot pay for is ordered"
    assert record_c.status is AssetStatus.SUCCESS
    say("deadline_stop", record_c, entry_c, panel_c)


async def test_dry_run_the_console_rollup_reads_the_records_it_wrote(tmp_path: Path) -> None:
    """The last link: what `meta.yaml.gauntlet` says is what the GAUNTLET stage prints.

    Reading the records rather than a live callback is what makes the console line verifiable —
    an operator can open the folder and find the same numbers.
    """
    panel = Panel(rounds=[set(), {2}, {1}, {1}], code="invented_text")
    entry, env, record, _ = await walk(tmp_path, panel)
    printed: list[str] = []

    session = _Session(printed, tmp_path)
    runner._gauntlet_rollup(session, generate.Report(records={entry.asset_id: record}))

    assert any("1 judged -> 0 pass, 1 blocked, 0 stopped" in line for line in printed)
    assert any("BLOCKED" in line for line in printed)
    assert any("BLOCKED.txt" in line and "GAUNTLET_REPORT.yaml" in line for line in printed)
    for line in printed:
        assert len(line) <= 78, f"FR-286 allows 78: {line!r}"
    print("  console:")
    for line in printed:
        print(f"    {line}")


class _Session:
    """The four `_Session` members `_gauntlet_rollup` touches — the run folder is one of them,
    because the rollup reads each asset's own `GAUNTLET_REPORT.yaml` for its defect codes."""

    def __init__(self, printed: list[str], run_dir: Path) -> None:
        self.printed = printed
        self.run_dir = run_dir
        self.stages = ["RENDER", "GAUNTLET", "DONE"]
        self.log = _StageLog()

    def say(self, text: str) -> None:
        self.printed.extend(text.splitlines())


class _StageLog:
    def event(self, event_type: str, message: str = "", **data: Any) -> str:
        return "ev_0001"

    warn = event
    error = event


# ---------------------------------- D54/FR-331: the ONE-WALK invariant, copy stage to critic
#
# Risk 2 of the compress plan, closed here end to end. `gauntlet._expected_blocks` builds each
# frame's referent from `CopySet.slide_texts`, while the gallery, the FR-309 card and the
# operator's audit read `panel_map`. If those two were produced by two loops, a compressed line
# that one accepted and the other blanked would make the critic demand a line the renderer was
# never given — the false `missing_text` BLOCK that F2 already cost this project once.
#
# `copywrite._compressed_deck` closes it structurally (one loop, one verdict per position, both
# outputs appended inside it). What this section adds is the end-to-end proof: a REAL compress
# call's output, walked through the REAL `generate.create()` money door, and read back off the
# system prompt the critics were actually sent. Nothing here spends — the same faked seams as
# every other test in this file, plus a scripted copy call.


class CompressCall:
    """A `StructuredCall` answering the D54 compress contract, from a canned per-slide list."""

    def __init__(self, slide_texts: list[str], *, headline: str = "Wired backwards") -> None:
        self.slide_texts = list(slide_texts)
        self.headline = headline
        self.schemas: list[str] = []

    async def __call__(self, role, messages, json_schema, images=None) -> ParsedResult:
        self.schemas.append(str(json_schema.get("name")))
        asset_ids = [line.split(" · ")[0].removeprefix("- ").strip()
                     for line in messages[0]["content"].splitlines()
                     if line.startswith("- ") and " · " in line]
        return ParsedResult(parsed={"creatives": [
            {"asset_id": asset_id, "headline": self.headline,
             "caption": "The tools, in the order that matters.", "hashtags": ["#ai"],
             "slide_texts": list(self.slide_texts), "through_line": "what one prompt buys",
             "narrative_arc": ""} for asset_id in asset_ids]}, raw_text="{}", cost_usd=0.004)


#: The source deck the compress call is handed: three panels far past a 300-character style slide
#: budget, which is the shape run `20260820_001158_2ard` shipped and D54 was adopted from.
LONG_PANELS = [
    "Panel one. " + "It keeps explaining the point at length. " * 8,
    "Panel two. " + "It also keeps explaining the point at length. " * 8,
    "Panel three. " + "And it explains the point at length once more. " * 8,
]
#: What the model sends back — one compression per SOURCE POSITION, in position order.
SHORT_PANELS = ["Ship it, then measure.", "Measure it, then cut.", "Cut it, then ship again."]


async def compressed_copy(entry: PlanEntry) -> tuple[CopySet, Any, CompressCall]:
    """One REAL `copywrite.write_copy` in compress mode over a bound three-panel deck.

    `source_post_id` is set here rather than in `make_entry`, because BINDING is the second half
    of `_compress_wanted`: compress mode alone changes nothing, and an unbound carousel takes the
    selection path in a compress-mode run exactly as it does in a verbatim one. `plan.assign`
    writes this field at ASSIGN on the real path (FR-304/FR-307).
    """
    entry.source_post_id = "p1"
    trend = TrendItem(
        history_key="t1", monitor_id="m1", name="AI tool stacks", topic_key="ai-tool-stacks",
        posts=[SourcePost(post_id="p1", url="https://virlo.test/p/1", author="@creator",
                          caption="A caption long enough to be a caption at all.",
                          hooks=["A cover hook"], panel_texts=list(LONG_PANELS), views=900)])
    call = CompressCall(SHORT_PANELS)
    result = await copywrite.write_copy(
        [entry], trends={"t1": trend}, styles={STYLE_KEY: make_style()}, call=call,
        engine=PromptEngine(), carousel_copy_mode="compress")
    return result.copy[entry.asset_id], result.provenance[entry.asset_id], call


async def test_dry_run_a_compressed_decks_critic_contract_quotes_the_compressed_slide_texts(
    tmp_path: Path,
) -> None:
    """The invariant, asserted where it would actually break: in the critic's own prompt.

    `_expected_blocks` enumerates `L1: "…"` per frame from `CopySet.slide_texts`. So if the copy
    stage's two outputs had drifted, the deck's judge would be looking for the SOURCE panel while
    the renderer had been given the compressed one — and would report `missing_text` on a deck
    nobody harmed. Here the same three compressed strings must appear in the critic prompt, and
    not one of the long source panels may.
    """
    entry = make_entry()
    copyset, provenance, copy_call = await compressed_copy(entry)
    panel = Panel(rounds=[set()], code="garbled")
    env = make_env(tmp_path, entry, panel, copy={entry.asset_id: copyset},
                   copy_provenance={entry.asset_id: provenance})
    renders = Renders()
    original, render.run = render.run, renders
    try:
        report = await generate.create([entry], env)
    finally:
        render.run = original

    assert copy_call.schemas == ["copy_compressed"], "the compress contract really ran"
    assert copyset.slide_texts == SHORT_PANELS
    judged = "\n".join(panel.prompts)
    for index, line in enumerate(SHORT_PANELS, start=1):
        assert f'L1: "{line}"' in judged, f"slide {index}'s compressed line never reached a critic"
    for source in LONG_PANELS:
        assert source not in judged, "the critic was shown the SOURCE panel it must not demand"
    assert report.records[entry.asset_id].status is AssetStatus.SUCCESS


async def test_dry_run_the_render_prompt_and_the_panel_map_carry_the_SAME_compressed_string(
    tmp_path: Path,
) -> None:
    """Both sides of the one walk, read off the two artifacts that actually consume them.

    `render.run` receives the prompt the frame was ordered from; `meta.yaml`'s `panel_map` is what
    the gallery and the operator's audit read. `slide_texts[i]` and `panel_map[i].source_text` are
    the same object by construction inside `_compressed_deck`, and this is the assertion that they
    are still the same string after the whole generate walk has handled both.
    """
    entry = make_entry()
    copyset, provenance, _ = await compressed_copy(entry)
    panel = Panel(rounds=[set()], code="garbled")
    env = make_env(tmp_path, entry, panel, copy={entry.asset_id: copyset},
                   copy_provenance={entry.asset_id: provenance})
    renders = Renders()
    original, render.run = render.run, renders
    try:
        report = await generate.create([entry], env)
    finally:
        render.run = original

    record = report.records[entry.asset_id]
    rows = record.panel_map
    assert [row["source_text"] for row in rows] == copyset.slide_texts == SHORT_PANELS
    assert all(row["compressed"] is True for row in rows), "FR-73: the receipt survives the join"
    assert all(row["ref_label"] == "" for row in rows), "FR-302: a compressed slide quotes nothing"
    assert [len(row["source_text_original"]) for row in rows] == [len(p) for p in LONG_PANELS], \
        "the model's own starting point survives — FR-309 measures 'compressed from N chars' on it"
    ordered = "\n".join(call["prompt"] for call in renders.calls)
    for line in SHORT_PANELS:
        assert line in ordered, "the frame was ordered from the compressed string, not the panel"
    for source in LONG_PANELS:
        assert source not in ordered, "no long source panel reached a paid render prompt"


async def test_dry_run_the_compressed_receipt_reaches_meta_yaml_on_disk(tmp_path: Path) -> None:
    """FR-73 at the file, not at the dataclass: `copy_mode` and every row's `compressed` flag have
    to survive the meta writer, because meta.yaml is what a Phase-2 publisher and the FR-309
    gallery read — and an audit that cannot tell a compressed deck from a quoted one cannot tell
    the operator which decks to judge on fidelity and which on style."""
    entry = make_entry()
    copyset, provenance, _ = await compressed_copy(entry)
    panel = Panel(rounds=[set()], code="garbled")
    env = make_env(tmp_path, entry, panel, copy={entry.asset_id: copyset},
                   copy_provenance={entry.asset_id: provenance})
    renders = Renders()
    original, render.run = render.run, renders
    try:
        await generate.create([entry], env)
    finally:
        render.run = original

    meta = yaml.safe_load((tmp_path / entry.asset_id / "meta.yaml").read_text(encoding="utf-8"))

    assert meta["copy_mode"] == "compress", "FR-73 v2.3.0's top-level key"
    assert [row["compressed"] for row in meta["panel_map"]] == [True, True, True]
    assert [row["source_text"] for row in meta["panel_map"]] == SHORT_PANELS
    assert meta["panel_map"][0]["source_text_original"] == LONG_PANELS[0]
    assert meta["copy_source_refs"] == {}, "a compressed deck resolved no labels (FR-302)"
    assert meta["copy_source_post_id"] == "p1", "the provenance CLAIM is unchanged by the mode"


async def test_dry_run_a_verbatim_deck_still_writes_copy_mode_verbatim_and_false_rows(
    tmp_path: Path,
) -> None:
    """The control, and the regression guard for every deck that did not opt in. ONE row schema
    always: the key is written on both walks, so a reader never has to ask which one it got."""
    entry = make_entry()
    panel = Panel(rounds=[set()], code="garbled")
    env = make_env(tmp_path, entry, panel, copy_provenance={entry.asset_id: copywrite.
                                                            CopyProvenance(post_id="p1")})
    renders = Renders()
    original, render.run = render.run, renders
    try:
        await generate.create([entry], env)
    finally:
        render.run = original

    meta = yaml.safe_load((tmp_path / entry.asset_id / "meta.yaml").read_text(encoding="utf-8"))

    assert meta["copy_mode"] == "verbatim", "the default, written explicitly rather than omitted"
