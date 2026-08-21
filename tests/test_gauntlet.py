"""The gauntlet loop against stubbed seams (spec §§1–3) — $0, no network, no provider.

Every test here drives `run_deck`/`run_single` with a scripted `StructuredCall`, a scripted
`RerenderFn` and a stub prompt engine, because that is exactly the shape the real call sites have:
the critics ride the LLM seam and the money lives inside the caller's closure. What is pinned:

- the round loop and FR-324's round-2 scoping (brief/craft narrow, `system` never does);
- the unavailable-critic semantics (drop for the DECK, degrade the gate, skip when all drop);
- FR-325's four terminal tiers, including leakage overriding both `fail_action` and a stop;
- the money seam's status mapping (`declined_*`/`halted` -> budget_stop/deadline_stop);
- `confidence: low` craft defects recorded but never failing;
- F8's confidence-keyed twin of that rule: a `confidence: low` SYSTEM defect still fails its frame
  and still buys its re-render, and only loses the power to block the deck at the end;
- F9-A's timing-keyed third door beside them: a tier-2 defect first heard in the FINAL round of a
  multi-round run, about a frame no round re-rendered, degrades instead of blocking — with each of
  its four conditions pinned on its own, and the two the loop cannot reach pinned on the predicate;
- `critic_empty_fail` read as a PASS;
- `fix_instruction`'s canned-remedy channel: dedupe, precedence, caps, fence line, sanitation.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from hypesocials import gauntlet
from hypesocials import prompts_engine as pe
from hypesocials.config import CriticConfig, GauntletConfig
from hypesocials.models import ParsedResult

#: The shipped prompt folder — the critic templates and the remedy sheet are pinned against the
#: real files, because "the allowlist matches the template" is only true of the file that ships.
PROMPTS = Path(pe.PROMPTS_DIR)


# --------------------------------------------------------------------------------------------
# Stubs — the three seams the module talks to
# --------------------------------------------------------------------------------------------


class _Engine:
    """A prompt engine with no files: the critic prompt always renders, the fix sheet may not."""

    def __init__(self, fix_text: str = "", broken: tuple[str, ...] = ()) -> None:
        self.fix_text = fix_text
        self.broken = broken  # roles that cannot be resolved at all (no file, no built-in)
        self.contexts: list[tuple[str, dict[str, str]]] = []

    def render(self, role: str, context: Any, **_kw: Any) -> str:
        if role in self.broken:
            raise LookupError(f"no template and no built-in for {role}")
        self.contexts.append((role, dict(context)))
        return f"SYSTEM<{role}>"

    def template(self, role: str, *, profile: str = "") -> Any:
        if role == gauntlet.FIX_TEMPLATE and self.fix_text:
            class _T:
                text = self.fix_text
                origin = "stub sheet"
            return _T()
        raise LookupError(role)


class _Call:
    """A scripted `StructuredCall`. `script` is one dict per ROUND: critic name -> answer.

    An answer is either a parsed payload (`dict`), the string `"degraded"` (the LLM seam already
    spent its own retry and came back unusable), or `"boom"` (an unregistered role).
    """

    def __init__(self, script: list[dict[str, Any]], *, cost: float = 0.01) -> None:
        self.script = script
        self.cost = cost
        self.rounds: dict[str, int] = {}
        self.seen: list[tuple[str, str, int, str]] = []  # (critic, role, images, expected_blocks)

    async def __call__(self, role: str, messages: list[dict[str, Any]],
                       json_schema: dict[str, Any], images: list[bytes] | None = None) -> Any:
        name = json_schema["name"].split("_", 1)[1]
        index = self.rounds[name] = self.rounds.get(name, 0) + 1
        self.seen.append((name, role, len(images or []), messages[0]["content"]))
        answer = self.script[min(index, len(self.script)) - 1].get(name, {"frames": []})
        if answer == "boom":  # this critic's own role is not registered; the shared one is
            if role != gauntlet.CRITIC_ROLE:
                raise ValueError(f"unknown LLM role {role!r}")
            answer = {"frames": [{"frame": slot, "pass": True, "defects": []}
                                 for slot in range(1, len(images or []) + 1)]}
        if answer == "degraded":
            return ParsedResult(parsed=None, raw_text="{", degraded=True, reason="truncated",
                                cost_usd=self.cost)
        return ParsedResult(parsed=answer, raw_text="{}", cost_usd=self.cost)


class _Rerender:
    """A scripted `RerenderFn`; `results` maps frame number -> the result it returns each time."""

    def __init__(self, results: dict[int, Any] | None = None, *, cost: float = 0.04,
                 tmp_path: Path | None = None) -> None:
        self.results = results or {}
        self.cost = cost
        self.tmp_path = tmp_path
        self.calls: list[tuple[int, str]] = []

    async def __call__(self, number: int, suffix: str) -> gauntlet.RerenderResult:
        self.calls.append((number, suffix))
        scripted = self.results.get(number)
        if isinstance(scripted, str):  # a status word: declined_budget, failed, halted, …
            return gauntlet.RerenderResult(status=scripted, cost_usd=0.0)
        if isinstance(scripted, gauntlet.RerenderResult):
            return scripted
        # A delivered re-render is a REAL new file — the next round loads it like any other frame.
        folder = self.tmp_path or Path(__file__).parent
        path = folder / f"slide_{number}.png"
        path.write_bytes(b"\x89PNG" + bytes([number, len(self.calls)]))
        return gauntlet.RerenderResult(
            status="delivered", frame=gauntlet.FrameUnderTest(number, path), cost_usd=self.cost)


class _Log:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def event(self, event_type: str, message: str = "", *, level: str = "info",
              **data: Any) -> str:
        self.events.append((event_type, level, data))
        return "ev_test"

    def warn(self, event_type: str, message: str = "", **data: Any) -> str:
        return self.event(event_type, message, level="warn", **data)

    def types(self) -> list[str]:
        return [row[0] for row in self.events]


# --------------------------------------------------------------------------------------------
# Fixtures / builders
# --------------------------------------------------------------------------------------------


def _cfg(**over: Any) -> GauntletConfig:
    cfg = GauntletConfig(critics={"brief": CriticConfig(), "system": CriticConfig(),
                                  "craft": CriticConfig()})
    return replace(cfg, **over) if over else cfg


def _frames(tmp_path: Path, count: int) -> list[gauntlet.FrameUnderTest]:
    out = []
    for number in range(1, count + 1):
        path = tmp_path / f"slide_{number}.png"
        path.write_bytes(b"\x89PNG" + bytes([number]))
        out.append(gauntlet.FrameUnderTest(number=number, source=path))
    return out


def _contract(count: int, **over: Any) -> gauntlet.DeckContract:
    frames = [gauntlet.FrameContract(number=n, body_lines=[f"LINE {n}"], counter=f"{n}/{count}")
              for n in range(1, count + 1)]
    return gauntlet.DeckContract(frames=frames, style_dna="flat neon", layout_zones="top/lower",
                                 platform="linkedin", **over)


def _answer(*per_frame: list[tuple[str, ...]]) -> dict[str, Any]:
    """A critic payload: one row per attached frame, each a list of `(code[, zone[, conf]])`."""
    frames = []
    for slot, defects in enumerate(per_frame, start=1):
        rows = [{"code": d[0], "zone": d[1] if len(d) > 1 else "full_frame",
                 "confidence": d[2] if len(d) > 2 else "high", "detail": "seen"} for d in defects]
        frames.append({"frame": slot, "pass": not rows, "defects": rows})
    return {"frames": frames}


def _clean(count: int) -> dict[str, Any]:
    return _answer(*[[] for _ in range(count)])


# --------------------------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------------------------


async def test_a_clean_deck_passes_in_one_round_and_never_re_renders(tmp_path: Path) -> None:
    call = _Call([{"brief": _clean(3), "system": _clean(3), "craft": _clean(3)}])
    rerender = _Rerender(tmp_path=tmp_path)
    report = await gauntlet.run_deck(_frames(tmp_path, 3), _contract(3), rerender,
                                    cfg=_cfg(), call=call, log=_Log(), engine=_Engine())
    assert report.result == "pass"
    assert len(report.rounds) == 1 and report.rerenders == 0
    assert rerender.calls == []
    assert report.critic_cost_usd == pytest.approx(0.03)  # three critics, one round
    assert report.rerender_cost_usd == 0.0 and not report.degraded_gate


async def test_a_failing_frame_is_re_rendered_and_the_second_round_passes(tmp_path: Path) -> None:
    call = _Call([{"brief": _answer([], [("missing_text", "lower")], []),
                   "system": _clean(3), "craft": _clean(3)},
                  {"brief": _clean(1), "system": _clean(3), "craft": _clean(1)}])
    rerender = _Rerender(tmp_path=tmp_path)
    log = _Log()
    report = await gauntlet.run_deck(_frames(tmp_path, 3), _contract(3), rerender,
                                    cfg=_cfg(), call=call, log=log, engine=_Engine())
    assert report.result == "pass"
    assert report.rerenders == 1 and [n for n, _ in rerender.calls] == [2]
    assert report.rerender_cost_usd == pytest.approx(0.04)
    assert report.rounds[0].failed_frames() == (2,)
    assert report.rounds[0].rerendered == (2,)  # spec §6's meta.yaml row
    assert "gauntlet_rerender" in log.types()


async def test_round_two_scopes_brief_and_craft_but_system_always_judges_every_frame(
    tmp_path: Path,
) -> None:
    """FR-324: the saving is real, and the cross-frame reader is exempt from it."""
    call = _Call([{"brief": _answer([], [("missing_text", "lower")], []), "system": _clean(3),
                   "craft": _clean(3)},
                  {"brief": _clean(1), "system": _clean(3), "craft": _clean(1)}])
    await gauntlet.run_deck(_frames(tmp_path, 3), _contract(3), _Rerender(tmp_path=tmp_path),
                            cfg=_cfg(), call=call, log=_Log(), engine=_Engine())
    round_two = {name: images for name, _role, images, _sys in call.seen[3:]}
    assert round_two == {"brief": 1, "craft": 1, "system": 3}


async def test_an_unparseable_critic_is_dropped_for_the_deck_and_degrades_the_gate(
    tmp_path: Path,
) -> None:
    call = _Call([{"brief": "degraded", "system": _clean(2), "craft": _clean(2)},
                  {"brief": _clean(2), "system": _clean(2), "craft": _clean(2)}])
    log = _Log()
    report = await gauntlet.run_deck(_frames(tmp_path, 2), _contract(2), _Rerender(tmp_path=tmp_path),
                                     cfg=_cfg(), call=call, log=log, engine=_Engine())
    assert report.result == "pass" and report.degraded_gate
    assert report.rounds[0].unavailable == ("brief",)
    assert "gauntlet_critic_unavailable" in log.types()
    # Dropped for the DECK: the round-1 degrade is the only brief call ever made.
    assert [name for name, *_ in call.seen].count("brief") == 1
    # …and its billed tokens are still accounted for.
    assert report.critic_cost_usd == pytest.approx(0.03)


async def test_when_every_critic_is_unavailable_the_deck_is_skipped_never_blocked(
    tmp_path: Path,
) -> None:
    call = _Call([{"brief": "degraded", "system": "degraded", "craft": "degraded"}])
    log = _Log()
    report = await gauntlet.run_deck(_frames(tmp_path, 2), _contract(2), _Rerender(tmp_path=tmp_path),
                                     cfg=_cfg(), call=call, log=log, engine=_Engine())
    assert report.result == "skipped" and report.shipped and report.degraded_gate


async def test_a_missing_critic_prompt_is_an_unavailable_critic_not_an_exception(
    tmp_path: Path,
) -> None:
    call = _Call([{"system": _clean(1), "craft": _clean(1)}])
    engine = _Engine(broken=("critic_brief.md",))
    report = await gauntlet.run_deck(_frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
                                     cfg=_cfg(), call=call, log=_Log(), engine=engine)
    assert report.result == "pass" and report.rounds[0].unavailable == ("brief",)


async def test_a_critic_that_fails_a_frame_with_no_defects_is_logged_and_read_as_a_pass(
    tmp_path: Path,
) -> None:
    payload = {"frames": [{"frame": 1, "pass": False, "defects": []}]}
    call = _Call([{"brief": payload, "system": _clean(1), "craft": _clean(1)}])
    log = _Log()
    rerender = _Rerender(tmp_path=tmp_path)
    report = await gauntlet.run_deck(_frames(tmp_path, 1), _contract(1), rerender,
                                     cfg=_cfg(), call=call, log=log, engine=_Engine())
    assert report.result == "pass" and rerender.calls == []
    assert "critic_empty_fail" in log.types()


async def test_a_low_confidence_craft_defect_is_recorded_but_never_fails_the_frame(
    tmp_path: Path,
) -> None:
    call = _Call([{"brief": _clean(2), "system": _clean(2),
                   "craft": _answer([], [("contrast", "card", "low")])}])
    rerender = _Rerender(tmp_path=tmp_path)
    report = await gauntlet.run_deck(_frames(tmp_path, 2), _contract(2), rerender,
                                     cfg=_cfg(), call=call, log=_Log(), engine=_Engine())
    assert report.result == "pass" and rerender.calls == []
    assert report.rounds[0].per_critic["craft"][1].defects[0].confidence == "low"
    assert report.rounds[0].failed_frames() == ()


async def test_an_unreadable_frame_is_dropped_and_never_shifts_a_verdict_onto_its_neighbour(
    tmp_path: Path,
) -> None:
    frames = _frames(tmp_path, 3)
    frames[0] = gauntlet.FrameUnderTest(number=1, source=tmp_path / "gone.png")
    # Two frames attach (2 and 3); the verdict names attachment slot 2, which is SLIDE 3.
    call = _Call([{"brief": _answer([], [("invented_text", "top")]), "system": _clean(2),
                   "craft": _clean(2)}])
    report = await gauntlet.run_deck(frames, _contract(3), _Rerender(tmp_path=tmp_path),
                                     cfg=_cfg(rounds_max=1), call=call, log=_Log(),
                                     engine=_Engine())
    assert report.rounds[0].failed_frames() == (3,)


# --------------------------------------------------------------------------------------------
# FR-325 — the four terminal tiers (cosmetic joined leakage/contract/craft in Session 5.6/F7)
# --------------------------------------------------------------------------------------------

#: How many rounds a TIER fixture runs, and why it is not 1.
#:
#: Session 5.8/F9-A grants a standing defect the degrade bucket when its `(frame, code)` pair was
#: first heard in the FINAL round on a frame no round re-rendered. A single-round run has that
#: shape by construction — no earlier round to have heard anything, no delivered re-render to point
#: at — and is excluded by the rule's own condition 0 (a run that judged fewer than two rounds had
#: no fix structure to be denied, so `rounds_max_image: 1` stays the judge-only gate spec §4 asks
#: for).
#:
#: These fixtures run two rounds anyway, so that what they pin does not lean on that exclusion.
#: `_Call`'s script repeats its last entry, so the same verdict comes back in round 2, and the
#: default `_Rerender` delivers — so round 1 raises the defect AND buys the frame its re-render,
#: failing F9-A's frame and pair conditions on their own terms. Each of these tests is about its
#: TIER, and at two rounds it stays about its tier whichever way the round-count guard later moves.
#: The grace itself is pinned by its own matrix (Session 5.8/W3).
_TIER_ROUNDS = 2


@pytest.mark.parametrize("code", sorted(gauntlet.LEAKAGE_CODES))
async def test_a_standing_leakage_defect_blocks_even_when_fail_action_says_degrade(
    tmp_path: Path, code: str
) -> None:
    call = _Call([{"brief": _answer([(code, "top")]), "system": _clean(1), "craft": _clean(1)}]
                 if code in gauntlet.BRIEF_CODES else
                 [{"brief": _clean(1), "system": _clean(1), "craft": _answer([(code,)])}])
    log = _Log()
    report = await gauntlet.run_deck(_frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
                                     cfg=_cfg(rounds_max=1, fail_action="degrade"), call=call,
                                     log=log, engine=_Engine())
    assert report.result == "blocked" and not report.shipped
    assert "gauntlet_blocked" in log.types()


async def test_a_standing_contract_defect_follows_fail_action(tmp_path: Path) -> None:
    for action, expected in (("block", "blocked"), ("degrade", "degraded")):
        call = _Call([{"brief": _clean(1), "system": _answer([("style_palette", "full_frame")]),
                       "craft": _clean(1)}])
        report = await gauntlet.run_deck(
            _frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
            cfg=_cfg(rounds_max=_TIER_ROUNDS, fail_action=action), call=call, log=_Log(),
            engine=_Engine())
        assert report.result == expected, action


async def test_a_craft_only_standing_failure_ships_tagged_unless_craft_blocks(
    tmp_path: Path,
) -> None:
    def script() -> list[dict[str, Any]]:
        return [{"brief": _clean(1), "system": _clean(1), "craft": _answer([("composition",)])}]

    report = await gauntlet.run_deck(_frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
                                     cfg=_cfg(rounds_max=1), call=_Call(script()), log=_Log(),
                                     engine=_Engine())
    assert report.result == "pass" and report.craft_only and report.shipped
    # …and the standing craft defects stay readable in the last round, which is where the report
    # and the gallery read the GAUNTLET_CRAFT tag's justification from.
    assert report.rounds[-1].per_critic["craft"][0].defects[0].code == "composition"

    strict = await gauntlet.run_deck(_frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
                                     cfg=_cfg(rounds_max=1, craft_blocks=True),
                                     call=_Call(script()), log=_Log(), engine=_Engine())
    assert strict.result == "blocked" and not strict.craft_only


def test_the_four_tiers_partition_the_frozen_vocabulary_with_no_code_in_two_of_them() -> None:
    """Session 5.6/F7-A moved ONE code between tiers; this is the guard on that arithmetic.

    `counter_placement` left `CONTRACT_CODES` for `COSMETIC_CODES`, and the tier sets are read by
    `_terminal` as a chain of `elif`s — so a code that fell into two sets would settle on whichever
    branch happens to be written first, and a code that fell into none would silently reach the
    craft-only PASS. The vocabularies themselves stay frozen (spec §3): the partition is over
    `ALL_CODES`, so re-adding `counter_placement` to the contract tier without removing it from
    the cosmetic one fails here rather than three weeks later as a blocked deck.
    """
    tiers = (gauntlet.LEAKAGE_CODES, gauntlet.CONTRACT_CODES, frozenset(gauntlet.CRAFT_CODES),
             gauntlet.COSMETIC_CODES)

    assert set().union(*tiers) == gauntlet.ALL_CODES, "a code belongs to no tier"
    assert sum(len(tier) for tier in tiers) == len(gauntlet.ALL_CODES), "a code sits in two tiers"
    assert gauntlet.COSMETIC_CODES == {"counter_placement"}
    assert "counter_placement" not in gauntlet.CONTRACT_CODES, "F7-A's move was reverted"
    # D65/FR-368's newcomer, pinned by TIER rather than by membership. `empty_element` buys a
    # re-render round and must never block a paid deck, so it belongs to the craft vocabulary and
    # to no other tier: an empty card is a rendering habit, not a leaked identity and not a broken
    # style contract. Putting it in either of those two sets would make a blank pill the reason a
    # finished deck goes unpublished.
    assert "empty_element" in gauntlet.CRAFT_CODES
    assert "empty_element" not in gauntlet.LEAKAGE_CODES, "a blank card never blocks a deck"
    assert "empty_element" not in gauntlet.CONTRACT_CODES, "a blank card never blocks a deck"
    assert "empty_element" not in gauntlet.COSMETIC_CODES, \
        "cosmetic is the counter-treatment carve-out alone; craft is the tier that re-renders"
    # The number is contract content even though its styling is not — the two halves of the F7
    # split live in different critics' vocabularies, which is what makes them separable at all.
    assert "counter_value" in gauntlet.CONTRACT_CODES and "counter_value" in gauntlet.BRIEF_CODES
    assert "counter_placement" in gauntlet.SYSTEM_CODES


async def test_a_standing_cosmetic_defect_degrades_and_ships_whatever_fail_action_says(
    tmp_path: Path,
) -> None:
    """FR-325 tier 3 (Session 5.6/F7-A): `counter_placement` alone cannot kill a deck.

    gpt-image-2 oscillates the deck's own position badge across re-renders — chip, then plain, then
    missing — so a deck whose ONLY standing defect is where that badge sits was dying on render
    churn the operator cannot spend their way out of. The outcome is exactly `fail_action: degrade`
    semantics, under BOTH values of the knob: the deck ships, `degraded_gate` hangs
    `GAUNTLET_DEGRADED` on it, and no `gauntlet_blocked` event fires — that event is the record of
    a deck that was NOT published, and firing it for a shipped deck would make the log lie.
    """
    for action in ("block", "degrade"):
        call = _Call([{"brief": _clean(1), "system": _answer([("counter_placement", "chip")]),
                       "craft": _clean(1)}])
        log = _Log()
        report = await gauntlet.run_deck(
            _frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
            cfg=_cfg(rounds_max=1, fail_action=action), call=call, log=log, engine=_Engine())
        assert report.result == "degraded" and report.shipped, action
        assert report.degraded_gate, f"{action}: the deck ships without saying it was degraded"
        assert not report.craft_only, f"{action}: a cosmetic degrade is not a craft-tagged pass"
        assert "gauntlet_blocked" not in log.types(), action
        # …and the defect stays readable where the report and the gallery show it.
        assert report.rounds[-1].per_critic["system"][0].defects[0].code == "counter_placement"


async def test_a_standing_counter_value_stays_contract_tier_and_still_blocks(
    tmp_path: Path,
) -> None:
    """The other half of the F7 split, and the reason the split is safe.

    A wrong or missing counter VALUE is contract content — the badge says slide 4 on slide 2, or
    says nothing at all — so it keeps tier 2 and keeps following `fail_action`. Only the brief
    critic can report it, only the system critic can report the placement, and the two codes are
    in different frozen vocabularies: the cosmetic carve-out cannot widen into the number.
    """
    for action, expected in (("block", "blocked"), ("degrade", "degraded")):
        call = _Call([{"brief": _answer([("counter_value", "chip")]), "system": _clean(1),
                       "craft": _clean(1)}])
        log = _Log()
        report = await gauntlet.run_deck(
            _frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
            cfg=_cfg(rounds_max=_TIER_ROUNDS, fail_action=action), call=call, log=log,
            engine=_Engine())
        assert report.result == expected, action
        assert report.shipped is (expected != "blocked"), action
        assert ("gauntlet_blocked" in log.types()) is (expected == "blocked"), action
        if expected == "blocked":
            blocked = next(data for event, _l, data in log.events if event == "gauntlet_blocked")
            assert blocked["tier"] == "contract"
        else:
            # A tier-2 degrade is NOT the cosmetic tier's degrade: it is the operator's own
            # `fail_action`, and it does not claim the gate was thinner than configured.
            assert not report.degraded_gate


async def test_a_contract_defect_standing_beside_the_cosmetic_one_blocks_the_deck(
    tmp_path: Path,
) -> None:
    """Tier order, stated as a test: contract is settled BEFORE cosmetic, so the cosmetic carve-out
    can only ever be the reason a deck ships when it is the ONLY thing standing.

    The `tier` field on `gauntlet_blocked` says which rung actually killed it, which is what an
    operator reads before deciding whether to re-run or to fix the brief.
    """
    call = _Call([{"brief": _clean(1),
                   "system": _answer([("counter_placement", "chip"),
                                      ("style_palette", "full_frame")]),
                   "craft": _clean(1)}])
    log = _Log()
    report = await gauntlet.run_deck(_frames(tmp_path, 1), _contract(1),
                                     _Rerender(tmp_path=tmp_path),
                                     cfg=_cfg(rounds_max=_TIER_ROUNDS),
                                     call=call, log=log, engine=_Engine())
    assert report.result == "blocked" and not report.shipped and not report.degraded_gate
    blocked = next(data for event, _level, data in log.events if event == "gauntlet_blocked")
    assert blocked["tier"] == "contract"
    assert blocked["codes"] == ["counter_placement", "style_palette"], \
        "the cosmetic code is still reported; it just is not what blocked"


async def test_craft_blocks_only_blocks_when_a_craft_defect_is_actually_standing(
    tmp_path: Path,
) -> None:
    """The tightened guard (`craft_blocks and codes & CRAFT_CODES`), in its three shapes.

    Before the cosmetic tier existed, reaching the `craft_blocks` branch could only mean craft, so
    the knob was read without asking what was standing. Now a cosmetic-ONLY set reaches it too —
    and `craft_blocks` is a decision about EXECUTION QUALITY, not about the render model's badge
    churn. An operator who turns it on is asking for a stricter deck, not for a deck that dies on
    a misplaced counter.
    """
    def script(*codes: tuple[str, ...]) -> list[dict[str, Any]]:
        return [{"brief": _clean(1), "system": _answer([("counter_placement", "chip")]),
                 "craft": _answer(list(codes))}]

    async def verdict(craft: tuple[tuple[str, ...], ...], *,
                      blocks: bool) -> tuple[gauntlet.GauntletReport, _Log]:
        log = _Log()
        report = await gauntlet.run_deck(
            _frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
            cfg=_cfg(rounds_max=1, craft_blocks=blocks), call=_Call(script(*craft)), log=log,
            engine=_Engine())
        return report, log

    lenient, _ = await verdict((("composition",),), blocks=False)
    assert lenient.result == "degraded" and lenient.degraded_gate, \
        "a craft opinion riding along does not cost the cosmetic tier its degrade"

    strict, log = await verdict((("composition",),), blocks=True)
    assert strict.result == "blocked"
    blocked = next(data for event, _level, data in log.events if event == "gauntlet_blocked")
    assert blocked["tier"] == "craft", "the block was bought by the craft knob, not by the badge"

    cosmetic_only, log = await verdict((), blocks=True)
    assert cosmetic_only.result == "degraded" and cosmetic_only.degraded_gate
    assert "gauntlet_blocked" not in log.types(), \
        "craft_blocks turned a cosmetic-only standing set into a block"


async def test_a_cosmetic_defect_still_buys_the_re_render_it_can_no_longer_block_for(
    tmp_path: Path,
) -> None:
    """Re-render targeting is UNCHANGED by the tier move — that is the whole point of F7-A.

    `counter_placement` still enters `standing`, still fails its frame and still spends a fix
    round with the canned badge remedy attached. What changed is only what happens when it
    is STILL standing after the last round: the deck ships tagged instead of dying. A tier move
    that had also stopped the fix would have made the defect invisible rather than survivable.
    """
    call = _Call([{"brief": _clean(3), "system": _answer([], [("counter_placement", "chip")], []),
                   "craft": _clean(3)},
                  {"brief": _clean(1), "system": _answer([], [("counter_placement", "chip")], []),
                   "craft": _clean(1)}])
    rerender = _Rerender(tmp_path=tmp_path)
    log = _Log()
    report = await gauntlet.run_deck(_frames(tmp_path, 3), _contract(3), rerender,
                                     cfg=_cfg(rounds_max=2), call=call, log=log, engine=_Engine())
    assert report.rerenders >= 1 and [n for n, _ in rerender.calls] == [2]
    assert report.rounds[0].failed_frames() == (2,) and report.rounds[0].rerendered == (2,)
    assert "Put the position badge in the same place" in rerender.calls[0][1], \
        "the fix round went out without the badge remedy the standing code selects"
    assert report.result == "degraded" and report.degraded_gate and report.shipped
    assert "gauntlet_blocked" not in log.types()


# --------------------------------------------------------------------------------------------
# FR-325 tier 3, the confidence-keyed door (Session 5.7/F8): a standing SYSTEM verdict the critic
# itself marked `confidence: low` degrades instead of blocking. Terminal-only and system-only.
# --------------------------------------------------------------------------------------------


async def test_a_standing_low_confidence_system_defect_degrades_and_ships_whatever_fail_action_says(
    tmp_path: Path,
) -> None:
    """FR-325 tier 3 reached by CONFIDENCE (Session 5.7/F8): an unsure critic cannot bin a deck.

    The cosmetic door beside this one is keyed by CODE (`counter_placement` at any confidence);
    this one is keyed by the verdict's own hedge. A system critic that says `low` about the deck's
    own consistency has told the operator it is not sure — and a fully rendered, fully paid-for
    deck must not go unpublished on that. The outcome is the cosmetic tier's exactly: the deck
    ships, `degraded_gate` hangs `GAUNTLET_DEGRADED` on it so nobody mistakes it for a clean pass,
    and no `gauntlet_blocked` event fires, because that event is the record of a deck that was NOT
    published. Both values of `fail_action`, because the demotion is not the operator's knob.
    """
    for action in ("block", "degrade"):
        call = _Call([{"brief": _clean(1),
                       "system": _answer([("style_consistency", "upper", "low")]),
                       "craft": _clean(1)}])
        log = _Log()
        report = await gauntlet.run_deck(
            _frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
            cfg=_cfg(rounds_max=_TIER_ROUNDS, fail_action=action), call=call, log=log,
            engine=_Engine())
        assert report.result == "degraded" and report.shipped, action
        assert report.degraded_gate, f"{action}: the deck ships without saying it was degraded"
        assert not report.craft_only, f"{action}: a demoted system verdict is not a craft pass"
        assert "gauntlet_blocked" not in log.types(), action
        # …and the verdict stays readable WITH its hedge, which is the whole justification for the
        # tag: the operator opens the report and sees what the critic was unsure about.
        defect = report.rounds[-1].per_critic["system"][0].defects[0]
        assert (defect.code, defect.confidence) == ("style_consistency", "low"), action
        # It failed its frame like any other defect — only the LAST WORD changed (`_fails` is
        # untouched by F8), which is what keeps it on the round line and in the fix channel.
        assert report.rounds[-1].failed_frames() == (1,), action


async def test_the_same_system_code_at_high_confidence_still_blocks_under_fail_action_block(
    tmp_path: Path,
) -> None:
    """The control for the test above: the same deck, the same code, the same zone — the ONLY
    difference is `confidence: "high"` instead of `"low"`, and that alone is what turns a shipped
    `degraded` back into a `blocked`.

    Stated as its own test because the demotion is a hedge-reader, not a code-reader:
    `style_consistency` is and stays a CONTRACT-tier code (`CONTRACT_CODES`), and a critic that is
    sure the deck's slides do not match each other still stops it.
    """
    call = _Call([{"brief": _clean(1),
                   "system": _answer([("style_consistency", "upper", "high")]),
                   "craft": _clean(1)}])
    log = _Log()
    report = await gauntlet.run_deck(
        _frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
        cfg=_cfg(rounds_max=_TIER_ROUNDS, fail_action="block"), call=call, log=log,
        engine=_Engine())
    assert report.result == "blocked" and not report.shipped and not report.degraded_gate
    blocked = next(data for event, _level, data in log.events if event == "gauntlet_blocked")
    assert blocked["tier"] == "contract"
    assert "style_consistency" in gauntlet.CONTRACT_CODES, "the demotion widened into the tier set"


async def test_one_code_low_on_one_frame_and_high_on_another_blocks_on_the_sure_verdict(
    tmp_path: Path,
) -> None:
    """The reason the terminal partition is over DEFECTS and not over a code SET.

    `style_consistency` is exactly the code a cross-frame reader repeats: it hedges about slide 1's
    mark placement and is certain about slide 2's. A partition built from `{d.code for d in
    standing}` cannot express that — the one code would land in whichever bucket the comprehension
    that reads it happens to fill — so this deck would either ship with a certain contract defect
    standing or block on a hedge, depending on nothing an operator can see. Per defect, the sure
    verdict blocks and the hedge rides along in the report.
    """
    call = _Call([{"brief": _clean(2),
                   "system": _answer([("style_consistency", "upper", "low")],
                                     [("style_consistency", "upper", "high")]),
                   "craft": _clean(2)}])
    log = _Log()
    report = await gauntlet.run_deck(
        _frames(tmp_path, 2), _contract(2), _Rerender(tmp_path=tmp_path),
        cfg=_cfg(rounds_max=_TIER_ROUNDS, fail_action="block"), call=call, log=log,
        engine=_Engine())
    assert report.result == "blocked" and not report.shipped and not report.degraded_gate
    blocked = next(data for event, _level, data in log.events if event == "gauntlet_blocked")
    assert blocked["tier"] == "contract"
    assert blocked["frames"] == [1, 2], "both frames failed; only one of them blocked"
    assert blocked["codes"] == ["style_consistency"], \
        "one code, two confidences — the code set alone cannot decide this deck"


async def test_a_low_confidence_system_defect_beside_a_high_confidence_contract_code_blocks(
    tmp_path: Path,
) -> None:
    """The demotion moves ONE defect and never the standing set around it.

    A brief-critic `missing_text` is contract content the critic is sure about; the system critic's
    hedge about consistency stands beside it. Tier 2 is settled from what is left after the
    demotion, and what is left here still blocks — the hedge cannot launder its neighbour.
    """
    call = _Call([{"brief": _answer([("missing_text", "lower")]),
                   "system": _answer([("style_consistency", "upper", "low")]),
                   "craft": _clean(1)}])
    log = _Log()
    report = await gauntlet.run_deck(
        _frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
        cfg=_cfg(rounds_max=_TIER_ROUNDS, fail_action="block"), call=call, log=log,
        engine=_Engine())
    assert report.result == "blocked" and not report.shipped
    blocked = next(data for event, _level, data in log.events if event == "gauntlet_blocked")
    assert blocked["tier"] == "contract"
    assert blocked["codes"] == ["missing_text", "style_consistency"], \
        "the demoted code is still reported; it just is not what blocked"


async def test_a_low_confidence_brief_defect_is_never_demoted_and_still_blocks(
    tmp_path: Path,
) -> None:
    """System-only, stated as a test: the brief critic's hedge buys nothing.

    A brief verdict is about contract CONTENT — a missing string, a leaked identity, the wrong
    counter value — and an uncertain critic there is exactly the one worth stopping for: the cost
    of publishing a slide that dropped an ordered line is not paid back by the cost of a re-run.
    The same `confidence: "low"` that ships a system verdict blocks this one.
    """
    call = _Call([{"brief": _answer([("missing_text", "lower", "low")]),
                   "system": _clean(1), "craft": _clean(1)}])
    log = _Log()
    report = await gauntlet.run_deck(
        _frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
        cfg=_cfg(rounds_max=_TIER_ROUNDS, fail_action="block"), call=call, log=log,
        engine=_Engine())
    assert report.result == "blocked" and not report.shipped and not report.degraded_gate
    blocked = next(data for event, _level, data in log.events if event == "gauntlet_blocked")
    assert blocked["tier"] == "contract"
    assert report.rounds[-1].per_critic["brief"][0].defects[0].confidence == "low"


async def test_a_low_confidence_system_defect_and_a_cosmetic_one_share_the_degrade_bucket(
    tmp_path: Path,
) -> None:
    """The two demotion causes are one tier, not two branches — a deck carrying both still ships.

    F7's cosmetic door (code-keyed, `counter_placement`) and F8's confidence door (hedge-keyed, any
    system code) both empty into `degrade_standing`, so a standing set made of one of each reaches
    tier 3 exactly once. A pair of separate branches would have raced here, and whichever lost
    would have taken the deck down with it.
    """
    call = _Call([{"brief": _clean(1),
                   "system": _answer([("counter_placement", "chip"),
                                      ("style_consistency", "upper", "low")]),
                   "craft": _clean(1)}])
    log = _Log()
    report = await gauntlet.run_deck(
        _frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
        cfg=_cfg(rounds_max=_TIER_ROUNDS, fail_action="block"), call=call, log=log,
        engine=_Engine())
    assert report.result == "degraded" and report.shipped and report.degraded_gate
    assert "gauntlet_blocked" not in log.types()
    assert sorted(d.code for d in report.rounds[-1].per_critic["system"][0].defects) == \
        ["counter_placement", "style_consistency"]


async def test_a_low_confidence_system_defect_still_buys_the_re_render_it_cannot_block_for(
    tmp_path: Path,
) -> None:
    """Terminal-ONLY, which is what makes F8 narrower than the craft critic's low-confidence rule.

    The craft rule suppresses the failure itself (`_fails`), so a low-confidence craft opinion
    never fails a frame and never buys a dollar of re-render. This one leaves the whole loop
    intact: the hedge fails its frame, enters `standing`, is named on the round line and spends
    its fix round with the canned consistency remedy attached — the deck gets every chance to fix
    itself first, and only the LAST word changed. A demotion that had also stopped the fix would
    have made the defect invisible rather than survivable.
    """
    call = _Call([{"brief": _clean(3),
                   "system": _answer([], [("style_consistency", "upper", "low")], []),
                   "craft": _clean(3)},
                  {"brief": _clean(1),
                   "system": _answer([], [("style_consistency", "upper", "low")], []),
                   "craft": _clean(1)}])
    rerender = _Rerender(tmp_path=tmp_path)
    log = _Log()
    report = await gauntlet.run_deck(_frames(tmp_path, 3), _contract(3), rerender,
                                     cfg=_cfg(rounds_max=2, fail_action="block"), call=call,
                                     log=log, engine=_Engine())
    assert report.rerenders == 1 and [n for n, _ in rerender.calls] == [2]
    assert report.rounds[0].failed_frames() == (2,) and report.rounds[0].rerendered == (2,)
    assert "Match slide 1 of this deck exactly in the upper area" in rerender.calls[0][1], \
        "the fix round went out without the consistency remedy the standing code selects"
    assert report.result == "degraded" and report.degraded_gate and report.shipped
    assert "gauntlet_blocked" not in log.types()


async def test_the_canary_two_deck_shape_now_ships_degraded_instead_of_blocking(
    tmp_path: Path,
) -> None:
    """The regression this change was bought for: canary #2, `output/20260819_181930_8e6d`.

    A seven-slide LinkedIn deck, three rounds, seven re-renders and half a dollar of re-render
    spend later, blocked on ONE round-3 verdict: system `style_consistency`, zone `upper`,
    `confidence: low`, frame 3 — "Obsidian logo placed inline beside headline rather than
    upper-right as on other frames". Every counter defect was already gone (F7), no leakage was
    ever raised, and the operator had a publishable deck they could not publish. This is that
    run's shape, scripted round for round:

    - round 1: frames 3–7 fail the cross-frame reader, frame 7 with a SURE verdict beside a hedge;
    - round 2: the fixes hold except frame 6, which comes back with a sure `style_layout` (plus a
      low-confidence craft `truncated` opinion, which never fails a frame);
    - round 3: nothing stands but the one hedge on frame 3 — and the deck ships tagged.

    The round-1 and round-2 SURE verdicts matter to the pin: the terminal policy reads `latest`,
    not the accumulated `standing`, so a certain defect that was actually fixed does not follow
    the deck to the end. What survives the last round is the only thing that gets to judge it.
    """
    low = ("style_consistency", "right", "low")
    call = _Call([{"brief": _clean(7), "craft": _clean(7),
                   "system": _answer([], [], [low], [low], [low], [low],
                                     [("style_consistency", "upper", "high"), low])},
                  {"brief": _clean(5),
                   # brief and craft are scoped to round 1's re-renders (3, 4, 5, 6, 7), so their
                   # attachment slot 4 is SLIDE 6 — the frame this round is actually about.
                   "craft": _answer([], [], [], [("truncated", "middle", "low")], []),
                   "system": _answer([], [], [], [], [],
                                     [("style_layout", "card", "high"),
                                      ("style_consistency", "lower", "low")], [])},
                  {"brief": _clean(1), "craft": _clean(1),
                   "system": _answer([], [], [("style_consistency", "upper", "low")],
                                     [], [], [], [])}])
    rerender = _Rerender(tmp_path=tmp_path)
    log = _Log()
    report = await gauntlet.run_deck(_frames(tmp_path, 7), _contract(7), rerender,
                                     cfg=_cfg(rounds_max=3, fail_action="block"), call=call,
                                     log=log, engine=_Engine())
    assert [verdict.failed_frames() for verdict in report.rounds] == [(3, 4, 5, 6, 7), (6,), (3,)]
    assert report.rerenders == 6 and [n for n, _ in rerender.calls] == [3, 4, 5, 6, 7, 6]
    assert report.result == "degraded" and report.shipped and report.degraded_gate
    assert "gauntlet_blocked" not in log.types(), "canary #2's deck is still unpublishable"
    survivor = report.rounds[-1].per_critic["system"][2].defects[0]
    assert (survivor.code, survivor.zone, survivor.confidence) == \
        ("style_consistency", "upper", "low")


async def test_a_frame_whose_re_render_failed_keeps_its_defect_into_the_terminal_policy(
    tmp_path: Path,
) -> None:
    call = _Call([{"brief": _answer([("identity_leak", "foot")]), "system": _clean(1),
                   "craft": _clean(1)}])
    report = await gauntlet.run_deck(
        _frames(tmp_path, 1), _contract(1), _Rerender({1: "failed"}, tmp_path=tmp_path),
        cfg=_cfg(rounds_max=2), call=call, log=_Log(), engine=_Engine())
    assert report.result == "blocked" and report.rerenders == 0


# --------------------------------------------------------------------------------------------
# FR-325 tier 3, the TIMING door (Session 5.8/F9-A): a standing defect nobody said out loud until
# the final round, about a frame no round ever re-rendered, joins the degrade bucket instead of
# blocking — FR-324's fix loop never ran for it. Four conditions, all required, and each has its
# own test below: (0) the run judged at least two rounds, (1) the frame is in no round's
# `rerendered`, (2) the (frame, code) PAIR was in no round before the last, (3) the code is not
# leakage. Terminal-only, and asked at the call site of tier-2 codes only.
# --------------------------------------------------------------------------------------------


def _round_verdict(index: int, per_critic: dict[str, list[tuple[int, tuple[Any, ...]]]],
                   rerendered: tuple[int, ...] = ()) -> gauntlet.RoundVerdict:
    """A hand-built round of history, for the predicate tests that reach past the loop.

    `per_critic` is `{critic: [(frame, (code | Defect, …)), …]}`. Codes may be bare strings or
    whole `Defect`s where a test needs to say something about confidence.
    """
    return gauntlet.RoundVerdict(
        round=index,
        per_critic={
            name: [gauntlet.FrameDefects(
                frame=frame,
                defects=tuple(d if isinstance(d, gauntlet.Defect) else gauntlet.Defect(code=d)
                              for d in codes))
                   for frame, codes in rows]
            for name, rows in per_critic.items()},
        rerendered=rerendered)


async def test_a_final_round_discovery_on_a_never_re_rendered_frame_degrades_and_ships(
    tmp_path: Path,
) -> None:
    """FR-325 tier 3 reached by TIMING (Session 5.8/F9-A): a verdict the deck was never given a
    chance to answer cannot be the verdict that kills it.

    The two doors beside this one ask WHAT was said — a cosmetic code (F7) or a hedged system
    verdict (F8). This one asks WHEN. Round 1 fails frame 2 and buys it a re-render; the last
    round clears frame 2 and the cross-frame reader — the only critic that never stops reading the
    whole deck (FR-324) — names frame 3 for the first time in the run, with a sure, contract-tier
    `style_consistency`. There is no round left to fix it in and there never was one: frame 3 sat
    through every round the loop had, clean, while the frames around it were re-rendered. That is
    the discovery asymmetry, and a fully rendered, fully paid-for deck must not die of it.

    The outcome is tier 3's exactly — the deck ships, `degraded_gate` hangs `GAUNTLET_DEGRADED` on
    it so nobody reads it as a clean pass, and no `gauntlet_blocked` event fires, because that
    event is the record of a deck that was NOT published. Under BOTH values of `fail_action`,
    because the grace is not the operator's knob.
    """
    for action in ("block", "degrade"):
        call = _Call([
            {"brief": _answer([], [("missing_text", "lower")], []), "system": _clean(3),
             "craft": _clean(3)},
            # The last round: brief and craft are scoped to the re-rendered frame 2 and clear it;
            # `system` reads all three and names frame 3 for the first time.
            {"brief": _clean(1), "craft": _clean(1),
             "system": _answer([], [], [("style_consistency", "upper", "high")])}])
        rerender = _Rerender(tmp_path=tmp_path)
        log = _Log()
        report = await gauntlet.run_deck(
            _frames(tmp_path, 3), _contract(3), rerender,
            cfg=_cfg(rounds_max=2, fail_action=action), call=call, log=log, engine=_Engine())
        assert report.result == "degraded" and report.shipped, action
        assert report.degraded_gate, f"{action}: the deck ships without saying it was degraded"
        assert not report.craft_only, f"{action}: a graced contract defect is not a craft pass"
        assert "gauntlet_blocked" not in log.types(), action
        # The history the predicate read, pinned beside the verdict: two rounds, and frame 3 in
        # neither `rerendered` list. If the loop ever starts re-rendering on the last round, this
        # deck stops being a discovery and this test says so before the grace silently widens.
        assert [verdict.rerendered for verdict in report.rounds] == [(2,), ()], action
        assert report.rounds[-1].failed_frames() == (3,), action
        # …and the graced defect stays readable where the report and the gallery show it, at the
        # confidence it was given: this is a SURE contract-tier verdict that shipped on timing
        # alone, which is exactly what an operator opening the report needs to see.
        survivor = report.rounds[-1].per_critic["system"][2].defects[0]
        assert (survivor.code, survivor.confidence) == ("style_consistency", "high"), action
        assert survivor.code in gauntlet.CONTRACT_CODES, \
            f"{action}: the grace widened into the tier set instead of moving one defect"


async def test_a_pair_already_raised_in_an_earlier_round_is_no_discovery_and_still_blocks(
    tmp_path: Path,
) -> None:
    """Condition 2, isolated: the loop DID hear this one in time, so it keeps tier 2.

    Round 1 names frames 2 and 3. Frame 3's re-render delivers; frame 2's comes back `failed`, so
    frame 2 never enters any round's `rerendered` list and condition 1 holds for it — the ONE
    reachable shape where the frame condition passes and the pair condition is what decides. The
    same `(2, style_consistency)` pair comes back in the final round, and a defect standing since
    round 1 is not news: the loop had its chance at it, spent a fix round on it or declined to,
    and either way the asymmetry F9-A answers never arose. `fail_action: block` is honoured.

    (The failed re-render is also the disclosed literal edge in condition 1: a frame whose fix
    crashed or came back `failed` reads as never-re-rendered, because `rerendered` records
    DELIVERIES. Condition 2 is what stops that edge from gracing a defect the run did try to fix.)
    """
    high = ("style_consistency", "upper", "high")
    call = _Call([{"brief": _clean(3), "craft": _clean(3), "system": _answer([], [high], [high])},
                  {"brief": _clean(1), "craft": _clean(1), "system": _answer([], [high], [])}])
    log = _Log()
    report = await gauntlet.run_deck(
        _frames(tmp_path, 3), _contract(3), _Rerender({2: "failed"}, tmp_path=tmp_path),
        cfg=_cfg(rounds_max=2, fail_action="block"), call=call, log=log, engine=_Engine())
    assert report.result == "blocked" and not report.shipped and not report.degraded_gate
    assert [verdict.rerendered for verdict in report.rounds] == [(3,), ()], \
        "frame 2's failed re-render must not count as a delivery"
    blocked = next(data for event, _level, data in log.events if event == "gauntlet_blocked")
    assert blocked["tier"] == "contract" and blocked["frames"] == [2]


async def test_a_final_round_defect_on_a_frame_this_run_re_rendered_is_never_graced(
    tmp_path: Path,
) -> None:
    """Condition 1, isolated: money and a canned remedy were already spent on this frame.

    Frame 2 fails round 1 on `style_palette`, is re-rendered, and comes back failing a DIFFERENT
    contract code — so the pair is genuinely new in the last round (condition 2 holds) and the
    only thing standing between it and the grace is that the frame HAD its fix attempt. Whatever
    is still wrong with it survived a re-render rather than missing one, which is the opposite of
    the case F9-A was written for. It blocks.
    """
    call = _Call([{"brief": _clean(2), "craft": _clean(2),
                   "system": _answer([], [("style_palette", "full_frame", "high")])},
                  {"brief": _clean(1), "craft": _clean(1),
                   "system": _answer([], [("style_consistency", "upper", "high")])}])
    rerender = _Rerender(tmp_path=tmp_path)
    log = _Log()
    report = await gauntlet.run_deck(_frames(tmp_path, 2), _contract(2), rerender,
                                     cfg=_cfg(rounds_max=2, fail_action="block"), call=call,
                                     log=log, engine=_Engine())
    assert report.result == "blocked" and not report.shipped and not report.degraded_gate
    assert [verdict.rerendered for verdict in report.rounds] == [(2,), ()]
    assert [n for n, _suffix in rerender.calls] == [2], "the frame really did get its fix round"
    blocked = next(data for event, _level, data in log.events if event == "gauntlet_blocked")
    assert blocked["tier"] == "contract" and blocked["codes"] == ["style_consistency"]


async def test_a_single_round_run_is_out_of_scope_and_keeps_the_full_tier_behaviour(
    tmp_path: Path,
) -> None:
    """Condition 0 (conductor ruling, Session 5.8/W1): where no fix loop ran, nothing was denied.

    A run that ends on round 1 satisfies conditions 1 and 2 VACUOUSLY — there is no earlier round
    to have heard anything and no delivered re-render to point at — so without this guard every
    tier-2 defect in every one-round run would be graced and `fail_action: block` would quietly
    become report-only. Two shipped configurations have exactly that shape and neither may be
    turned into a rubber stamp behind the operator's back:

    - `rounds_max_image: 1`, the DEFAULT for standalone images and reel seed frames (spec §4: "a
      lone frame that needs three rounds is a copy problem"). That ceiling buys a judge-only gate
      on purpose — the frame is judged, and a contract defect stops it — not a report;
    - `rounds_max: 1` on a deck, which is an operator asking for the same thing explicitly.

    Both are pinned here, and both must read `blocked` under `fail_action: block`.
    """
    call = _Call([{"brief": _clean(1), "craft": _clean(1),
                   "system": _answer([("style_palette", "full_frame", "high")])}])
    log = _Log()
    deck = await gauntlet.run_deck(_frames(tmp_path, 1), _contract(1),
                                   _Rerender(tmp_path=tmp_path),
                                   cfg=_cfg(rounds_max=1, fail_action="block"), call=call,
                                   log=log, engine=_Engine())
    assert deck.result == "blocked" and not deck.shipped and not deck.degraded_gate
    assert len(deck.rounds) == 1, "the guard is about the round COUNT — this run must have one"
    blocked = next(data for event, _level, data in log.events if event == "gauntlet_blocked")
    assert blocked["tier"] == "contract" and blocked["rounds"] == 1

    # The standalone-image shape: the ceiling arrives as `rounds_max_image`, `run_single` takes
    # the minimum, and the same one-round exclusion holds.
    frame_call = _Call([{"brief": _clean(1), "craft": _clean(1),
                         "system": _answer([("style_layout", "top", "high")])}])
    image_log = _Log()
    image = await gauntlet.run_single(
        _frames(tmp_path, 1)[0], _contract(1), _Rerender(tmp_path=tmp_path),
        cfg=_cfg(rounds_max=3, rounds_max_image=1, fail_action="block"), call=frame_call,
        log=image_log, engine=_Engine())
    assert image.result == "blocked" and not image.shipped and not image.degraded_gate
    assert len(image.rounds) == 1 and image.rerenders == 0
    assert "gauntlet_blocked" in image_log.types()


async def test_a_leakage_defect_first_heard_in_the_final_round_still_blocks(
    tmp_path: Path,
) -> None:
    """Condition 3, at the loop level: a name, a face or a competitor's mark never ships, ever.

    Round 1 fails frame 2 on contract CONTENT; the re-render fixes that and comes back with an
    `identity_leak` nobody had raised before — a brand-new pair in the final round, on the one
    frame `fail_action: degrade` would otherwise have let through. The leakage tier is settled
    before every other branch and answers to no knob, no stop and no grace.

    Note what this run canNOT be: the leak stands on a RE-RENDERED frame, and it cannot stand on
    anything else. From round 2 on, brief and craft see only the frames the previous round
    re-rendered (FR-324's scoping) and `scoped = rerendered` in the loop, so a brief-only code —
    which every `LEAKAGE_CODES` member is — is structurally unable to name a virgin frame late.
    That is precisely why `_final_round_discovery`'s leakage carve-out is defensive rather than
    load-bearing today, and why it is pinned at the predicate level too (see the predicate test
    below): a future round policy must not be able to make it reachable and silent at once.
    """
    call = _Call([{"brief": _answer([], [("missing_text", "lower")], []), "system": _clean(3),
                   "craft": _clean(3)},
                  {"brief": _answer([("identity_leak", "foot")]), "craft": _clean(1),
                   "system": _clean(3)}])
    log = _Log()
    report = await gauntlet.run_deck(_frames(tmp_path, 3), _contract(3),
                                     _Rerender(tmp_path=tmp_path),
                                     cfg=_cfg(rounds_max=2, fail_action="degrade"), call=call,
                                     log=log, engine=_Engine())
    assert report.result == "blocked" and not report.shipped
    blocked = next(data for event, _level, data in log.events if event == "gauntlet_blocked")
    assert blocked["tier"] == "leakage" and blocked["codes"] == ["identity_leak"]
    assert gauntlet.LEAKAGE_CODES.isdisjoint(gauntlet.CONTRACT_CODES), \
        "leakage reaching the tier the grace is asked about would put the two in one bucket"


async def test_the_grace_is_scoped_to_the_frame_code_pair_and_not_to_the_code_alone(
    tmp_path: Path,
) -> None:
    """Condition 2 is about a PAIR, and this is the deck that shows why it has to be.

    `style_consistency` is the code a cross-frame reader repeats: round 1 says it about frame 2,
    which is re-rendered and comes back clean, and the last round says the same word about frame
    3 for the first time. A code-scoped history would read "we have heard this before" and block a
    frame nobody had ever mentioned; the pair-scoped one sees frame 3's verdict for what it is —
    news, on a frame the loop never touched — and ships the deck tagged.
    """
    high = ("style_consistency", "upper", "high")
    call = _Call([{"brief": _clean(3), "craft": _clean(3), "system": _answer([], [high], [])},
                  {"brief": _clean(1), "craft": _clean(1), "system": _answer([], [], [high])}])
    log = _Log()
    report = await gauntlet.run_deck(_frames(tmp_path, 3), _contract(3),
                                     _Rerender(tmp_path=tmp_path),
                                     cfg=_cfg(rounds_max=2, fail_action="block"), call=call,
                                     log=log, engine=_Engine())
    assert report.result == "degraded" and report.shipped and report.degraded_gate
    assert "gauntlet_blocked" not in log.types()
    assert [verdict.rerendered for verdict in report.rounds] == [(2,), ()]
    assert report.rounds[-1].failed_frames() == (3,), "the earlier frame's fix held"


async def test_a_craft_only_deck_keeps_its_craft_tag_and_is_never_offered_the_grace(
    tmp_path: Path,
) -> None:
    """The narrowing at the call site, from the side it protects: `GAUNTLET_CRAFT` is not
    `GAUNTLET_DEGRADED`, and F9-A must not blur the two.

    `_terminal` asks the grace of `CONTRACT_CODES` defects ONLY, because the grace exists to stop
    a BLOCK and a craft-only standing set was already shipping as a tagged PASS. The degrade
    bucket sits ABOVE the craft-only branch, so a craft defect that had been allowed into it would
    come out `degraded` with `degraded_gate` set — a deck the operator reads as "the gate was
    thinner than configured" when what actually happened is "one execution opinion stands". That
    is a worse report for a deck that ships either way, which is the whole reason the narrowing is
    at the call site rather than inside the predicate.

    Here the last round's only standing defect is a craft `composition` first heard in that round,
    and the deck comes out `pass` + `craft_only`, with `degraded_gate` clear.
    """
    call = _Call([{"brief": _answer([], [("missing_text", "lower")], []), "system": _clean(3),
                   "craft": _clean(3)},
                  {"brief": _clean(1), "system": _clean(3), "craft": _answer([("composition",)])}])
    log = _Log()
    report = await gauntlet.run_deck(_frames(tmp_path, 3), _contract(3),
                                     _Rerender(tmp_path=tmp_path),
                                     cfg=_cfg(rounds_max=2, fail_action="block"), call=call,
                                     log=log, engine=_Engine())
    assert report.result == "pass" and report.craft_only and report.shipped
    assert not report.degraded_gate, "a craft-only pass must not be relabelled a degraded gate"
    assert "gauntlet_blocked" not in log.types()
    assert report.rounds[-1].per_critic["craft"][0].defects[0].code == "composition"
    assert "composition" in gauntlet.CRAFT_CODES and "composition" not in gauntlet.CONTRACT_CODES


async def test_the_canary_three_deck_shape_now_ships_degraded_instead_of_blocking(
    tmp_path: Path,
) -> None:
    """The regression this change was bought for: canary #3, `output/20260819_191734_0jc2`.

    A four-frame deck the operator said they were satisfied with, blocked by the round-3 verdict
    on frame 4 — a frame that passed rounds 1 and 2 cleanly and that no round ever re-rendered.
    Re-rendering frames 2 and 3 toward the deck MOVED the consistency baseline, so the last round
    is exactly where a cross-frame reader is most likely to name an untouched frame for the first
    time, and by then the round budget was spent. That run's shape, round for round:

    - round 1: frame 2 hedges `style_consistency`, frame 3 is sure about it; both are re-rendered;
    - round 2: frame 2's fix holds, frame 3 is still sure; frame 3 alone is re-rendered;
    - round 3: frames 2 and 3 are clean and FRAME 4 — never named, never re-rendered — comes back
      with a sure `style_consistency` and a `counter_placement` beside it.

    Both of frame 4's defects reach the degrade bucket by different doors: the consistency verdict
    by F9-A's timing grace, the badge by F7's cosmetic tier. Nothing is left in `contract_standing`
    and the deck ships tagged. The round history is pinned because it is the input the grace reads:
    if `rerendered` ever stopped recording what each round actually delivered, this deck would
    silently go back to blocking.
    """
    low = ("style_consistency", "right", "low")
    high = ("style_consistency", "upper", "high")
    call = _Call([
        {"brief": _clean(4), "craft": _clean(4), "system": _answer([], [low], [high], [])},
        # brief and craft are scoped to round 1's re-renders (2, 3); system reads all four.
        {"brief": _clean(2), "craft": _clean(2), "system": _answer([], [], [high], [])},
        {"brief": _clean(1), "craft": _clean(1),
         "system": _answer([], [], [], [high, ("counter_placement", "chip")])}])
    rerender = _Rerender(tmp_path=tmp_path)
    log = _Log()
    report = await gauntlet.run_deck(_frames(tmp_path, 4), _contract(4), rerender,
                                     cfg=_cfg(rounds_max=3, fail_action="block"), call=call,
                                     log=log, engine=_Engine())
    assert [verdict.failed_frames() for verdict in report.rounds] == [(2, 3), (3,), (4,)]
    assert [verdict.rerendered for verdict in report.rounds] == [(2, 3), (3,), ()]
    assert report.rerenders == 3 and [n for n, _suffix in rerender.calls] == [2, 3, 3]
    assert report.result == "degraded" and report.shipped and report.degraded_gate
    assert "gauntlet_blocked" not in log.types(), "canary #3's deck is still unpublishable"
    survivors = sorted(d.code for d in report.rounds[-1].per_critic["system"][3].defects)
    assert survivors == ["counter_placement", "style_consistency"]


def test_the_grace_predicate_answers_the_shapes_the_loop_itself_cannot_reach() -> None:
    """`_final_round_discovery` read directly, on histories `run_deck` cannot build.

    Two of the four conditions are unreachable end to end today, and both are unreachable for the
    same reason: from round 2 on, brief and craft judge only the frames the previous round
    re-rendered (FR-324), so no critic but `system` can name a virgin frame late, and every
    leakage and craft code belongs to one of those two. That makes the leakage carve-out
    (condition 3) and the code-agnosticism the call-site narrowing relies on invisible to any
    test that drives the loop — which is exactly the shape a guard rots in. `RoundVerdict` is a
    plain frozen dataclass and the predicate is a pure function over a sequence of them, so the
    histories are built here by hand and the predicate is asked directly.

    What is pinned: the predicate is a statement about WHEN a defect was heard and about nothing
    else (a craft code on a qualifying history is graced by it — the tier narrowing lives at the
    call site, not in here), with leakage the single code-shaped exception; a sighting counts even
    where it did not FAIL its frame; and conditions 0, 1 and 2 each answer on their own.
    """
    consistency = gauntlet.Defect(code="style_consistency")
    # Two rounds. Round 1 names frame 2 and re-renders it; the final round clears frame 2 and
    # names frame 3 — never re-rendered, never mentioned before. The canonical graced shape.
    history = [
        _round_verdict(1, {"brief": [(1, ()), (2, ()), (3, ())],
                           "system": [(1, ()), (2, ("style_consistency",)), (3, ())]},
                       rerendered=(2,)),
        _round_verdict(2, {"brief": [(2, ())],
                           "system": [(1, ()), (2, ()), (3, ("style_consistency",))]})]
    assert gauntlet._final_round_discovery(3, consistency, history)

    # Code-agnostic by design: a craft code on the same history is graced by the PREDICATE. What
    # keeps a craft-only deck's `GAUNTLET_CRAFT` tag is `_terminal` asking only about tier 2.
    assert gauntlet._final_round_discovery(3, gauntlet.Defect(code="composition"), history)
    # …except leakage, which is carved out inside the predicate so no call site can re-open it.
    for code in sorted(gauntlet.LEAKAGE_CODES):
        assert not gauntlet._final_round_discovery(3, gauntlet.Defect(code=code), history), code

    # Condition 0: the same final round, alone, is not a discovery — it is a one-round run.
    assert not gauntlet._final_round_discovery(3, consistency, history[-1:])
    # Condition 1: frame 2 was re-rendered, so its verdicts are never graced…
    assert not gauntlet._final_round_discovery(2, consistency, history)
    # …and condition 2 holds independently — a pair heard in round 1 on a frame nothing ever
    # re-rendered is not news either.
    untouched = [replace(history[0], rerendered=()), history[1]]
    assert not gauntlet._final_round_discovery(2, consistency, untouched)

    # A sighting counts even where it did not FAIL its frame: a `confidence: low` craft opinion is
    # still the critic having said the word out loud in an earlier round, so the same pair coming
    # back at the end is not a discovery. The question is whether the defect is NEWS.
    hedged = [
        _round_verdict(1, {"craft": [(3, (gauntlet.Defect(code="truncated", confidence="low"),))]},
                       rerendered=(2,)),
        _round_verdict(2, {"craft": [(3, ("truncated",))]})]
    assert not gauntlet._final_round_discovery(3, gauntlet.Defect(code="truncated"), hedged)


# --------------------------------------------------------------------------------------------
# The money seam
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status, expected", [
    ("declined_budget", "budget_stop"), ("declined_deck_budget", "budget_stop"),
    ("declined_runway", "deadline_stop"), ("halted", "deadline_stop")])
async def test_a_declined_re_render_maps_onto_its_own_stop_result(
    tmp_path: Path, status: str, expected: str
) -> None:
    call = _Call([{"brief": _clean(1), "system": _answer([("style_layout", "top")]),
                   "craft": _clean(1)}])
    log = _Log()
    report = await gauntlet.run_deck(
        _frames(tmp_path, 1), _contract(1), _Rerender({1: status}, tmp_path=tmp_path),
        cfg=_cfg(rounds_max=3), call=call, log=log, engine=_Engine())
    assert report.result == expected and report.rerenders == 0
    assert f"gauntlet_{expected}" in log.types()


async def test_a_stop_never_launders_a_leakage_defect_into_a_shippable_result(
    tmp_path: Path,
) -> None:
    """Spec §2's mapped stop and §7's "terminal per tier policy", read together: the leakage tier
    always blocks, so running out of money with a competitor's mark on a slide ships nothing."""
    call = _Call([{"brief": _answer([("forbidden_mark", "chip")]), "system": _clean(1),
                   "craft": _clean(1)}])
    report = await gauntlet.run_deck(
        _frames(tmp_path, 1), _contract(1), _Rerender({1: "declined_budget"}, tmp_path=tmp_path),
        cfg=_cfg(rounds_max=3), call=call, log=_Log(), engine=_Engine())
    assert report.result == "blocked"


async def test_every_re_render_dollar_is_summed_including_a_frame_that_came_back_failed(
    tmp_path: Path,
) -> None:
    call = _Call([{"brief": _answer([("missing_text",)], [("missing_text",)]),
                   "system": _clean(2), "craft": _clean(2)},
                  {"brief": _clean(1), "system": _clean(2), "craft": _clean(1)}])
    rerender = _Rerender({2: gauntlet.RerenderResult(status="failed", cost_usd=0.02)},
                          tmp_path=tmp_path)
    report = await gauntlet.run_deck(_frames(tmp_path, 2), _contract(2), rerender,
                                     cfg=_cfg(rounds_max=2), call=call, log=_Log(),
                                     engine=_Engine())
    assert report.rerenders == 1  # frame 1 delivered, frame 2 came back failed but was billed
    assert report.rerender_cost_usd == pytest.approx(0.06)


async def test_a_re_render_closure_that_raises_leaves_the_frame_failed_and_never_propagates(
    tmp_path: Path,
) -> None:
    """A caller-side crash is contained: no exception escapes, nothing is counted as delivered,
    the frame carries its defect into the terminal policy, and the deck is BLOCKED on it.

    The crash is also the closest thing the suite has to F9-A's excluded shape, which is why the
    round history is pinned beside the verdict. A crashed re-render never reaches `rerendered`, and
    a crash ends the loop (nothing moved, so another round would judge the same pixels) — so this
    defect stands on a frame that, as far as the history can tell, was never re-rendered and was
    never named before the last round. What keeps it blocking is F9-A's condition 0: the run judged
    ONE round, so it had no fix structure to be denied, and the grace is not offered. A deck that
    lost its fix round to a crash is not a deck that was told it did not need one.
    """
    class _Boom(_Rerender):
        async def __call__(self, number: int, suffix: str) -> gauntlet.RerenderResult:
            raise RuntimeError("caller-side crash")

    call = _Call([{"brief": _answer([("missing_text",)]), "system": _clean(1), "craft": _clean(1)}])
    report = await gauntlet.run_deck(_frames(tmp_path, 1), _contract(1), _Boom(tmp_path=tmp_path),
                                     cfg=_cfg(rounds_max=2), call=call, log=_Log(),
                                     engine=_Engine())
    assert report.result == "blocked" and report.rerenders == 0
    assert len(report.rounds) == 1 and report.rounds[0].rerendered == (), \
        "a crashed closure is not a delivery, and the round says so"
    assert report.rounds[-1].per_critic["brief"][0].defects[0].code == "missing_text", \
        "the frame kept its defect through the crash"


# --------------------------------------------------------------------------------------------
# run_single
# --------------------------------------------------------------------------------------------


async def test_run_single_takes_the_lower_of_the_two_round_ceilings(tmp_path: Path) -> None:
    """A standalone frame's ceiling is the LOWER of the two, whichever way round they are.

    This is the rule the anchor pre-gate stands on: it replaces BOTH values (FR-324 grants it one
    extra round) precisely because `run_single` takes the minimum, so a config that gates
    standalone images at one round cannot silently take the cover's fix round back — and a deck
    ceiling of 3 cannot widen a standalone frame past its own.
    """
    frame = _frames(tmp_path, 1)[0]
    call = _Call([{"brief": _answer([("garbled",)]), "system": _clean(1), "craft": _clean(1)}])
    report = await gauntlet.run_single(frame, _contract(1), _Rerender(tmp_path=tmp_path),
                                       cfg=_cfg(rounds_max=3, rounds_max_image=1), call=call,
                                       log=_Log(), engine=_Engine())
    assert len(report.rounds) == 1 and report.rerenders == 0

    call = _Call([{"brief": _answer([("garbled",)]), "system": _clean(1), "craft": _clean(1)}])
    anchor = await gauntlet.run_single(
        frame, _contract(1), _Rerender(tmp_path=tmp_path),
        cfg=_cfg(rounds_max=1, rounds_max_image=3,
                 critics={"brief": CriticConfig(), "craft": CriticConfig()}),
        call=call, log=_Log(), engine=_Engine())
    assert len(anchor.rounds) == 1
    assert "system" not in anchor.rounds[0].per_critic  # the pre-gate runs brief + craft only


async def test_a_disabled_or_empty_panel_skips_rather_than_blocking(tmp_path: Path) -> None:
    off = _cfg(critics={"brief": CriticConfig(enabled=False), "system": CriticConfig(enabled=False),
                        "craft": CriticConfig(enabled=False)})
    report = await gauntlet.run_deck(_frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
                                     cfg=off, call=_Call([]), log=_Log(), engine=_Engine())
    assert report.result == "skipped"


# --------------------------------------------------------------------------------------------
# The critics' context and schema
# --------------------------------------------------------------------------------------------


async def test_each_critic_gets_its_own_enum_and_a_strict_schema(tmp_path: Path) -> None:
    call = _Call([{"brief": _clean(1), "system": _clean(1), "craft": _clean(1)}])
    engine = _Engine()
    await gauntlet.run_deck(_frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
                            cfg=_cfg(rounds_max=1), call=call, log=_Log(), engine=engine)
    for name, codes in gauntlet.CRITIC_CODES.items():
        schema = gauntlet._schema(name)["schema"]
        defect = schema["properties"]["frames"]["items"]["properties"]["defects"]
        assert defect["items"]["properties"]["code"]["enum"] == list(codes)
        assert defect["maxItems"] == 3
        assert schema["additionalProperties"] is False
        assert defect["items"]["required"] == ["code", "zone", "confidence", "detail"]


async def test_a_per_critic_model_override_rides_its_own_role_and_falls_back_when_unregistered(
    tmp_path: Path,
) -> None:
    """`StructuredCall` takes a ROLE, never a model id, so a per-critic model reaches the wire as
    `critic:<name>`. An unregistered role must cost the deck a call, never a critic."""
    cfg = _cfg(critics={"brief": CriticConfig(model="anthropic/claude-haiku-5"),
                        "system": CriticConfig(), "craft": CriticConfig(enabled=False)})
    call = _Call([{"brief": "boom", "system": _clean(1)}])
    report = await gauntlet.run_deck(_frames(tmp_path, 1), _contract(1),
                                     _Rerender(tmp_path=tmp_path), cfg=cfg, call=call,
                                     log=_Log(), engine=_Engine())
    roles = [(name, role) for name, role, *_rest in call.seen]
    assert ("brief", "critic:brief") in roles  # the override's own role is tried first…
    assert ("brief", gauntlet.CRITIC_ROLE) in roles  # …and the shared role catches the fall
    assert ("system", gauntlet.CRITIC_ROLE) in roles and len(roles) == 3
    assert report.result == "pass" and report.rounds[0].unavailable == ()
    assert "craft" not in report.rounds[0].per_critic  # a disabled critic is never called


async def test_the_contract_reaches_the_critics_as_enumerated_line_blocks(tmp_path: Path) -> None:
    contract = gauntlet.DeckContract(
        frames=[gauntlet.FrameContract(number=1, body_lines=["FIRST", "SECOND"], counter="1/2",
                                       signature="HypeDigitaly", is_list=True,
                                       truncation_suspect=True),
                gauntlet.FrameContract(number=2, wordless_reason="empty_panel")],
        required_marks=["Notion"], forbidden_terms=["Acme"], platform="linkedin")
    call = _Call([{"brief": _clean(2), "system": _clean(2), "craft": _clean(2)}])
    engine = _Engine()
    await gauntlet.run_deck(_frames(tmp_path, 2), contract, _Rerender(tmp_path=tmp_path),
                            cfg=_cfg(rounds_max=1), call=call, log=_Log(), engine=engine)
    blocks = dict(engine.contexts)["critic_brief.md"]["expected_blocks"]
    assert 'L1: "FIRST"' in blocks and 'L2: "SECOND"' in blocks
    assert 'counter: "1/2"' in blocks and 'signature: "HypeDigitaly"' in blocks
    assert "frame 2 (slide 2):" in blocks and "wordless by mandate (empty_panel)" in blocks
    assert "truncation suspected" in blocks
    assert dict(engine.contexts)["critic_brief.md"]["forbidden_terms"] == "Acme"


async def test_fr366_a_mark_is_demanded_on_its_own_frame_and_exempted_across_the_deck(
    tmp_path: Path,
) -> None:
    """D65/FR-366: the union SANCTIONS, the per-frame rows ACCUSE, and they are not the same list.

    `required_marks` has to stay deck-wide — it is why a real logo's brand colours are not a
    palette defect and its own lettering is not invented text, on whichever frame it turns up. But
    read as a demand it says every frame owes every mark, and that is how the 08-21 audit came to
    report `missing_mark` on slides 02, 03 and 07 of a deck whose source showed that logo on slide
    05 alone — after which the fix round drew one there to satisfy it.
    """
    contract = gauntlet.DeckContract(
        frames=[gauntlet.FrameContract(number=1, body_lines=["FIRST"]),
                gauntlet.FrameContract(number=2, body_lines=["SECOND"])],
        required_marks=["Notion", "Figma"], frame_marks={1: ["Notion"], 2: ["Figma"]},
        platform="linkedin")
    call = _Call([{"brief": _clean(2), "system": _clean(2), "craft": _clean(2)}])
    engine = _Engine()
    await gauntlet.run_deck(_frames(tmp_path, 2), contract, _Rerender(tmp_path=tmp_path),
                            cfg=_cfg(rounds_max=1), call=call, log=_Log(), engine=engine)

    context = dict(engine.contexts)["critic_brief.md"]
    assert context["required_marks"] == "Notion, Figma", "the exemption list stays the union"
    first, second = context["expected_blocks"].split("\n\n")
    assert "marks: Notion" in first and "marks: Figma" not in first
    assert "marks: Figma" in second and "marks: Notion" not in second


async def test_a_frame_that_was_ordered_no_mark_carries_no_marks_row_at_all(
    tmp_path: Path,
) -> None:
    """The silent half of FR-366: no row means no demand, and the templates say so in words.

    An empty `marks:` row would read to a critic as a mark it could not name rather than as a
    frame that owes none — and it would cost a line of prompt on every wordless slide in the run.
    """
    contract = gauntlet.DeckContract(
        frames=[gauntlet.FrameContract(number=1, body_lines=["FIRST"])],
        required_marks=["Notion"], frame_marks={}, platform="linkedin")
    call = _Call([{"brief": _clean(1), "system": _clean(1), "craft": _clean(1)}])
    engine = _Engine()
    await gauntlet.run_deck(_frames(tmp_path, 1), contract, _Rerender(tmp_path=tmp_path),
                            cfg=_cfg(rounds_max=1), call=call, log=_Log(), engine=engine)

    assert "marks:" not in dict(engine.contexts)["critic_brief.md"]["expected_blocks"]


#: D65/FR-367, pinned as text because it is text that does the work. Each row is
#: `(template, a phrase that MUST be there, a phrase that must NOT be)` — the "must not" side is
#: the withdrawn wording, so a future edit that quietly restores it fails here rather than in a
#: paid run. `""` on either side means "nothing to assert in that direction".
_REBALANCE: tuple[tuple[str, str, str], ...] = (
    # The brief critic's when-unsure bar for everything that is not leakage. The leakage paragraph
    # above it keeps its own when-unsure-FAIL, which the next row pins.
    ("critic_brief.md", "For every other code, when unsure, PASS.",
     "For everything else, report what you can actually see."),
    ("critic_brief.md", "when unsure, FAIL", ""),
    # `platform_chrome` is tier 1 and blocks a deck past `fail_action: degrade`, so it may only
    # cover a REAL platform's own furniture. A stylised illustration was blocking whole decks.
    ("critic_brief.md", "A REAL social platform's own furniture", "an invented app UI"),
    # The three content checks the audit went through unflagged: 15 fabricated benchmark numbers,
    # one sentence rendered six times, and a numbered ladder with a step missing.
    ("critic_brief.md", "1. NUMERALS.", ""),
    ("critic_brief.md", "2. DUPLICATION.", ""),
    ("critic_brief.md", "3. ORDINALS.", ""),
    # And the per-frame marks rule the row above builds on.
    ("critic_brief.md", "carries a `marks:` row naming it", ""),
    # The style critic's pedantry damping: about two thirds of the audit's standing defects were
    # band heights and card widths, spent out of the same re-render budget the content needed.
    ("critic_system.md", "MEASUREMENTS ARE NOT YOUR SUBJECT.", ""),
    ("critic_system.md", "Never spend this deck's", ""),
    # A line that simply stops is truncation too, with nothing visibly sliced.
    ("critic_craft.md", "Or grammatically: a line that simply", ""),
)


@pytest.mark.parametrize(("role", "present", "absent"), _REBALANCE)
def test_fr367_the_critic_rebalance_ships_in_both_copies_of_every_template(
    role: str, present: str, absent: str,
) -> None:
    """FR-183: a prompt lives in TWO places, and a rule that reaches only one of them is a rule
    that silently disappears the moment a template file is unreadable — the one moment nobody is
    reading the prompt. `test_template_parity` proves the two copies agree; this proves WHAT they
    agree on, in the words D65 decided."""
    for text in ((PROMPTS / role).read_text(encoding="utf-8"), pe._BUILT_INS[role]):
        assert present in text, f"{role}: the FR-367 rule is missing"
        assert not absent or absent not in text, f"{role}: the withdrawn wording is still here"


async def test_each_critic_gets_exactly_the_context_its_shipped_template_names(
    tmp_path: Path,
) -> None:
    """The context is narrowed to the role's own allowlist, which is in turn exactly the set the
    shipped prompt uses — so no critic can be handed contract data its verdict has no use for,
    and no template can name a value that was never built."""
    call = _Call([{"brief": _clean(1), "system": _clean(1), "craft": _clean(1)}])
    engine = _Engine()
    await gauntlet.run_deck(_frames(tmp_path, 1), _contract(1), _Rerender(tmp_path=tmp_path),
                            cfg=_cfg(rounds_max=1), call=call, log=_Log(), engine=engine)
    built = {role: set(context) for role, context in engine.contexts}
    assert built == {
        "critic_brief.md": {"expected_blocks", "forbidden_terms", "list_mode", "required_marks",
                            "sanctioned_illegible", "style_dna"},
        "critic_system.md": {"expected_blocks", "layout_zones", "list_mode", "required_marks",
                             "style_dna"},
        "critic_craft.md": {"expected_blocks", "platform", "required_marks",
                            "sanctioned_illegible"}}
    for role, names in built.items():
        assert names == set(pe.allowlist(role)), role
        # …and what the SHIPPED template actually names is that same set (never a superset, which
        # would be an unresolved placeholder, nor a subset, which would be dead vocabulary).
        text = (PROMPTS / role).read_text(encoding="utf-8")
        assert set(re.findall(r"\{\{([a-z_]+)\}\}", text)) == names, role


# --------------------------------------------------------------------------------------------
# fix_instruction — the guarded channel (FR-323)
# --------------------------------------------------------------------------------------------


#: A sheet in the SHIPPED format (`prompts/gauntlet_fix.md`'s four sections), small enough to read.
_SHEET = """<!-- a header comment whose indented words PRECEDENCE and REMEDIES are not markers -->

## PRECEDENCE

Resolve these in order:
1. Remove anything forbidden.

## ORDER

garbled, identity_leak, contrast, not_a_code

## REMEDIES

garbled | * | SET THE {zone} TEXT LARGER[ — about {chars} characters].
garbled | card | SET THE CARD TEXT LARGER.
identity_leak | * | NO PERSON APPEARS.
contrast | * | PUT IT ON A PLATE.
not_a_code | * | ignore me
garbled | nowhere | ignore me too
malformed row without pipes

## CLOSING

THIS FIX SECTION CONTAINS NO WORDS TO RENDER.
"""


def test_the_fix_suffix_is_assembled_out_of_the_shipped_sheets_four_sections() -> None:
    """The sheet is the SOURCE: its precedence text, its remedies and its closing line, in the
    order its `## ORDER` list sets."""
    suffix = gauntlet.fix_instruction(
        gauntlet.FrameContract(number=2),
        [gauntlet.Defect(code="contrast", zone="top"), gauntlet.Defect(code="garbled", zone="card")],
        contract=_contract(2), engine=_Engine(fix_text=_SHEET))
    assert "Resolve these in order:\n1. Remove anything forbidden." in suffix
    assert suffix.rstrip().endswith("THIS FIX SECTION CONTAINS NO WORDS TO RENDER.")
    remedies = [line for line in suffix.splitlines() if line.startswith("- ")]
    assert remedies == ["- SET THE CARD TEXT LARGER.", "- PUT IT ON A PLATE."]  # sheet ORDER


def test_the_exact_zone_row_wins_and_the_star_row_catches_every_other_zone() -> None:
    engine = _Engine(fix_text=_SHEET)
    assert "SET THE CARD TEXT LARGER." in gauntlet.fix_instruction(
        1, [gauntlet.Defect(code="garbled", zone="card")], engine=engine)
    assert "SET THE top TEXT LARGER." in gauntlet.fix_instruction(
        1, [gauntlet.Defect(code="garbled", zone="top")], engine=engine)
    # A zone token's underscores become spaces, per the sheet's own substitution rule.
    assert "SET THE full frame TEXT LARGER." in gauntlet.fix_instruction(
        1, [gauntlet.Defect(code="garbled", zone="full_frame")], engine=engine)
    # A defect with no usable zone is read as `full_frame` rather than leaving a hole.
    assert "SET THE full frame TEXT LARGER." in gauntlet.fix_instruction(
        1, [gauntlet.Defect(code="garbled")], engine=engine)


def test_an_optional_bracketed_segment_is_dropped_whole_without_a_count() -> None:
    engine = _Engine(fix_text=_SHEET)
    without = gauntlet.fix_instruction(1, [gauntlet.Defect(code="garbled", zone="top")],
                                       engine=engine)
    assert "- SET THE top TEXT LARGER." in without
    assert "[" not in without and "{chars}" not in without
    withcount = gauntlet.fix_instruction(1, [gauntlet.Defect(code="garbled", zone="top")],
                                         engine=engine, invented_chars=42)
    assert "SET THE top TEXT LARGER — about 42 characters." in withcount
    assert "[" not in withcount


def test_an_absent_or_unparseable_sheet_falls_back_to_the_built_ins_and_never_raises() -> None:
    for engine in (None, _Engine(), _Engine(fix_text="## REMEDIES\n\nnothing parseable here\n")):
        suffix = gauntlet.fix_instruction(1, [gauntlet.Defect(code="garbled", zone="top")],
                                          engine=engine)
        assert "Draw the top lettering once, cleanly" in suffix
        assert gauntlet.PRECEDENCE_BLOCK in suffix
        assert suffix.rstrip().endswith(gauntlet.FENCE_LINE)


def test_the_shipped_sheet_is_the_one_the_module_actually_assembles_from() -> None:
    """End-to-end against `prompts/gauntlet_fix.md` itself: all 21 codes ordered, all 42 rows
    parsed (39 + the D59 `style_consistency | chip` row that refuses to propagate an unmandated
    chip from slide 1 + D65's two `empty_element` rows), and the two verbatim blocks
    byte-identical to the module's stand-in constants.

    The two counts move only when the FROZEN vocabulary itself moves, which is the point of
    asserting them: v2.9.0/D65 added `empty_element` (FR-368) and had to touch the code tuple, the
    sheet's `## ORDER` line, the sheet's remedy rows, `_REMEDIES`, `_PRECEDENCE` and both critic
    templates in the same change — a partial edit lands here, on the numbers, rather than on a
    live deck whose fix suffix silently dropped a remedy it had no sentence for."""
    from hypesocials.prompts_engine import PromptEngine

    sheet = gauntlet._sheet(PromptEngine())
    assert sheet.origin.endswith("gauntlet_fix.md")
    assert set(sheet.order) == gauntlet.ALL_CODES and len(sheet.order) == 21
    assert len(sheet.remedies) == 42
    assert all((code, "") in sheet.remedies for code in gauntlet.ALL_CODES)  # every code has a `*`
    assert sheet.precedence == gauntlet.PRECEDENCE_BLOCK
    assert sheet.closing == gauntlet.FENCE_LINE
    suffix = gauntlet.fix_instruction(
        1, [gauntlet.Defect(code="invented_text", zone="card"),
            gauntlet.Defect(code="identity_leak", zone="foot")], engine=PromptEngine())
    remedies = [line for line in suffix.splitlines() if line.startswith("- ")]
    assert remedies[0].startswith("- No person's name")  # identity_leak leads the sheet's ORDER
    assert "The card in this frame carried lettering" in remedies[1]  # the card-specific row
    assert "[" not in suffix and "{" not in suffix


def test_the_shipped_sheets_precedence_forbids_the_collateral_loss_of_a_sanctioned_mark() -> None:
    """F7-C: a re-render that fixes ONE defect must not drop the badge on its way past.

    Session 5.5's live decks lost the FR-313 position badge as collateral — the model was told to
    fix a contrast defect and returned a frame with the counter gone, which the system critic then
    reported as `counter_placement` and the deck died on. The remedy sheet's PRECEDENCE block is
    emitted verbatim into EVERY fix suffix, so naming the badge there is the one place the guard
    reaches every re-render regardless of which defect bought it.

    Matched against the flattened text: the sheet is hand-wrapped prose, and a re-wrap must not be
    able to break a pin on a sentence that did not change.

    D59 (SESSION J) narrowed the guard by one word: "a QUOTED position badge". The unnarrowed
    sentence preserved an INVENTED chip across every re-render that did not name `counter_value`
    (run `20260820_145809_4a0q`), which is the opposite of F7-C's intent — the badge this guard
    protects is the one the TEXT block quotes; a chip the TEXT block never quoted is "not quoted in
    the TEXT block" under precedence item 1 and goes.
    """
    from hypesocials.prompts_engine import PromptEngine

    guard = ("Fix only the named defects; everything else stays as rendered, a quoted position "
             "badge and every sanctioned mark included.")
    sheet = gauntlet._sheet(PromptEngine())

    assert guard in " ".join(sheet.precedence.split()), \
        "the shipped sheet's precedence lost F7-C's collateral-loss guard"
    assert guard in " ".join(gauntlet.PRECEDENCE_BLOCK.split()), \
        "the built-in twin drifted from the file — re-sync it"
    # And it travels: the guard is in the assembled suffix of a fix that is about something else
    # entirely, which is the case it was written for.
    suffix = gauntlet.fix_instruction(1, [gauntlet.Defect(code="contrast", zone="card")],
                                      engine=PromptEngine())
    assert guard in " ".join(suffix.split())


def test_the_fix_reservation_is_measured_off_the_loaded_sheet_and_never_a_constant() -> None:
    """F1-C's reservation is a RELATIONSHIP to the sheet, which is why F7-C could lengthen the
    precedence block without a number to chase.

    `prompts/gauntlet_fix.md` is operator-overridable (FR-183) and only its REMEDIES are capped —
    the precedence block and the closing fence are emitted verbatim at whatever length the sheet
    writes them. So the reservation is asserted as its own arithmetic over the LOADED sheet, and
    as an upper bound on the longest suffix the channel can actually assemble. Pinning the shipped
    figure instead would describe today's sheet and quietly under-reserve for an edited one — the
    same defect one indirection later.
    """
    from hypesocials.prompts_engine import PromptEngine

    engine = PromptEngine()
    sheet = gauntlet._sheet(engine)

    assert gauntlet.fix_reserve(engine) == (
        len(gauntlet._FIX_HEADER) + gauntlet._FIX_MAX_CHARS + len(sheet.precedence)
        + len(sheet.closing) + gauntlet._FIX_JOIN_CHARS + gauntlet._SUFFIX_SEPARATOR_CHARS)
    # The reservation MOVES with the sheet: a precedence block 40 characters longer reserves 40
    # characters more, which is the property that lets an operator edit the file safely.
    edited = _SHEET.replace("1. Remove anything forbidden.",
                            "1. Remove anything forbidden." + " x" * 20)
    assert (gauntlet.fix_reserve(_Engine(fix_text=edited))
            - gauntlet.fix_reserve(_Engine(fix_text=_SHEET))) == 40
    # …and it is an upper bound: three capped remedies plus the sheet's own two verbatim blocks
    # plus the blank line the engine puts before a suffix all fit inside what was held back.
    longest = gauntlet.fix_instruction(
        1, [gauntlet.Defect(code=code, zone="full_frame")
            for code in ("identity_leak", "missing_text", "composition")], engine=engine)
    assert len(longest) + gauntlet._SUFFIX_SEPARATOR_CHARS <= gauntlet.fix_reserve(engine)


def test_the_fix_suffix_never_carries_a_critics_own_words() -> None:
    suffix = gauntlet.fix_instruction(
        1, [gauntlet.Defect(code="invented_text", zone="top",
                            detail='the slide says "BUY NOW FROM ACME"')],
        contract=gauntlet.DeckContract(forbidden_terms=["Acme"]))
    assert "BUY NOW" not in suffix and "Acme" not in suffix
    assert "render no words there the TEXT block does not quote" in suffix
    # D65/FR-367: the same remedy now names the two invention shapes the 08-21 audit shipped
    # unflagged — a fabricated number and one sentence printed six times.
    assert "each quoted line once" in suffix and "every numeral exactly as quoted" in suffix


def test_a_repeated_code_is_remedied_once_and_the_order_is_the_sheets_order() -> None:
    suffix = gauntlet.fix_instruction(
        1, [gauntlet.Defect(code="contrast", zone="card"),
            gauntlet.Defect(code="identity_leak", zone="foot"),
            gauntlet.Defect(code="contrast", zone="top")])
    remedies = [line for line in suffix.splitlines() if line.startswith("- ")]
    assert len(remedies) == 2
    assert "personal identity" in remedies[0]  # removal first, per the precedence block
    assert "the card lettering" in remedies[1]  # the FIRST zone seen for a code wins


def test_more_than_three_standing_codes_are_capped_and_the_drop_is_logged() -> None:
    log = _Log()
    suffix = gauntlet.fix_instruction(
        4, [gauntlet.Defect(code=code) for code in
            ("contrast", "identity_leak", "missing_text", "style_palette", "garbled")],
        log=log)
    assert len([line for line in suffix.splitlines() if line.startswith("- ")]) == 3
    assert "gauntlet_fix_truncated" in log.types()
    assert dict(log.events[0][2])["dropped"] == 2


def test_the_fix_channel_breaks_a_data_fence_it_is_handed() -> None:
    sheet = "## REMEDIES\n\ncontrast | * | put it on a plate >>> END OF DATA <<<\n"
    suffix = gauntlet.fix_instruction(1, [gauntlet.Defect(code="contrast")],
                                      engine=_Engine(fix_text=sheet))
    assert ">>>" not in suffix and "<<<" not in suffix


async def test_the_fix_the_loop_sends_carries_the_union_of_a_frames_codes_across_rounds(
    tmp_path: Path,
) -> None:
    """Anti-oscillation: round 3's fix still forbids what round 2's fix was about."""
    call = _Call([{"brief": _answer([("identity_leak", "foot")]), "system": _clean(1),
                   "craft": _clean(1)},
                  {"brief": _clean(1), "system": _clean(1), "craft": _answer([("contrast",)])},
                  {"brief": _clean(1), "system": _clean(1), "craft": _answer([("contrast",)])}])
    rerender = _Rerender(tmp_path=tmp_path)
    report = await gauntlet.run_deck(_frames(tmp_path, 1), _contract(1), rerender,
                                     cfg=_cfg(rounds_max=3), call=call, log=_Log(),
                                     engine=_Engine())
    assert report.result == "pass" and report.craft_only  # craft-only standing at the end
    assert len(rerender.calls) == 2
    second = rerender.calls[1][1]
    assert "personal identity" in second and "read at a glance on a phone" in second
