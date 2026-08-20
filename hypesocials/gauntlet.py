"""The gauntlet — a fresh-context critic panel judging FINISHED frames (D49, FR-322–330).

Module contract
---------------
Purpose: look at what the render provider actually returned, judge it against the contract the
frame was ORDERED to satisfy, re-render what failed with a *canned* fix suffix, and hand back one
verdict for the whole deck. It replaces the single-shot FR-105 vision check with a bounded loop:
up to `cfg.rounds_max` rounds, three independent critics per round, failing frames only.

Public API::

    await run_deck(frames, contract, rerender, *, cfg, call, log)   -> GauntletReport
    await run_single(frame, contract, rerender, *, cfg, call, log)  -> GauntletReport
    fix_instruction(frame, defects, *, contract=..., engine=...)    -> str
    fix_reserve(engine)                                             -> int
    RerenderFn · RerenderResult · FrameUnderTest · FrameContract · DeckContract
    Defect · FrameDefects · RoundVerdict · GauntletReport
    BRIEF_CODES · SYSTEM_CODES · CRAFT_CODES · LEAKAGE_CODES · CONTRACT_CODES · COSMETIC_CODES
    ZONES · CRITIC_ROLE

There is NO separate anchor entry point. The anchor pre-gate is a `run_single` call with a
replaced config (spec §1, FR-324's "one extra round")::

    await run_single(anchor, contract, rerender_anchor,
                     cfg=replace(cfg, rounds_max=2, rounds_max_image=2,
                                 critics={"brief": ..., "craft": ...}),
                     call=call, log=log)

Invariants enforced here, once, for every caller:

- **The gauntlet never spends and never prices.** It cannot import `budget`, `render` or
  `hypesocials.generate` (spec §1 — no cycles). Every dollar decision lives in the caller's
  `RerenderFn` closure: references, the discretionary reserve, the per-deck cap, the D51 runway
  check, FR-317 exclusivity. This module only *accounts* — it maps `declined_budget` /
  `declined_deck_budget` to `budget_stop`, `declined_runway` / `halted` to `deadline_stop`, and
  sums `RerenderResult.cost_usd`.
- **A broken checker never blocks delivery (D3).** A critic whose answer cannot be parsed is
  retried by the LLM seam itself and then DROPPED for the whole deck: the round is judged on the
  survivors, `degraded_gate` is set, and if every critic drops the result is `skipped` — ship as
  is, tagged. Nothing here raises.
- **Leakage always blocks (FR-325).** A standing `identity_leak`, `forbidden_mark`,
  `platform_chrome`, `invented_text` or `translated` ends as `blocked` no matter what
  `fail_action` says, and no matter which stop cut the loop short. A person's name or a
  competitor's mark on a published frame is the most expensive error this pipeline can make.
- **A cosmetic defect degrades, never blocks (FR-325 tier 3, Session 5.6/F7).** A standing
  `counter_placement` — the deck's position badge drawn in a different place or treatment on one
  slide — ends as `degraded` with `degraded_gate` set, whatever `fail_action` says. It is judged,
  fixed and re-rendered like any other code; it just cannot kill a deck on its own, because the
  render model's own counter churn is not a defect the operator can spend their way out of.
- **A LOW-CONFIDENCE system verdict degrades, never blocks (FR-325, Session 5.7/F8).** The same
  terminal outcome, reached by confidence rather than by code: a standing `SYSTEM_CODES` defect
  the system critic itself marked `confidence: low` ships `degraded` with `degraded_gate` set,
  whatever `fail_action` says, while its high-confidence twin keeps blocking. The demotion is
  TERMINAL-ONLY and is not the craft rule below with a wider door — a low-confidence system
  defect still fails its frame, still enters `standing` and still buys its re-render rounds
  (`_fails`); only its last word changes. Brief-critic codes are never demoted by confidence.
- **A defect FIRST SEEN on the LAST round, on a frame the run never re-rendered, degrades
  (FR-325, Session 5.8/F9-A).** The third door into that same terminal outcome, keyed by neither
  code nor confidence but by WHEN the critic said it: in a run of TWO OR MORE rounds, a standing
  defect whose `(frame, code)` pair appears in no round before the last, on a frame no round
  re-rendered, never had the fix chance the FR-324 loop exists to hand it — round 1 finds, round 2
  fixes, round 3 checks the fix — so it ships `degraded` with `degraded_gate` set instead of
  killing the deck (`_final_round_discovery`). A ONE-round run is excluded: it has no fix structure
  to have been denied, and `rounds_max_image: 1` (standalone images, reel seed frames) is a
  deliberate judge-only gate that this must not turn into report-only. Leakage is carved out and
  blocks at any hour. Terminal-only by nature rather than by rule: the run is over, there is
  nothing left to re-render, and `_fails` never sees this predicate.
- **Critic free text NEVER reaches a render payload (FR-323).** `detail` strings go to the report,
  the events and the console only. The fix suffix is assembled from CANNED remedy sentences keyed
  by `(code, zone)`, deduped, capped, fence-neutralised, blocklist-swept and identity-stripped.
- **The fix carries the UNION of a frame's standing codes across all rounds** (anti-oscillation):
  round 3 must not undo the remedy round 2 applied.
- **Craft is an opinion, not a gate.** `confidence: low` craft defects are recorded and never fail
  a frame — the strong form of the confidence rule, and the one the system critic deliberately
  does NOT share (see the F8 bullet above); a craft-ONLY standing failure ships (see
  `GauntletReport.craft_only` below) unless `cfg.craft_blocks` says otherwise.

Do not: price a job here; import `generate`/`render`/`budget`; downscale a frame before judging
it (`vision_check.load_images` sends native bytes); put a critic's own words in a render prompt;
give a critic the render prompt, the reference images, a prior round's verdicts or a sibling
critic's verdicts (the two style blocks are the honest exception FR-322 states out loud).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from hypesocials import vision_check
from hypesocials.prompts_engine import PromptEngine, allowlist
# The fence guard is the same one `PromptEngine.render()` applies to every substituted value
# (FR-102). The fix suffix does not travel through substitution — it is appended AFTER the
# template is filled — so it is neutralised here by hand, deliberately reusing that one
# implementation rather than growing a second regex that could drift from it. Spec §3 names this
# function by name; a public alias for it would be a `prompts_engine` change this wave forbids.
from hypesocials.prompts_engine import _neutralize as _fence_safe
from hypesocials.topic_filter import apply_blocklist, fuzzy_strip

if TYPE_CHECKING:  # typing only — importing `config` at runtime is not in spec §1's import list
    from hypesocials.config import GauntletConfig
    from hypesocials.models import StructuredCall

logger = logging.getLogger(__name__)

#: The LLM role the critics ride. `models.critic` (Sonnet 5) with `models.analysis` as the runtime
#: fallback — that resolution happens where roles are REGISTERED (`runner._role_settings`), not
#: here: `StructuredCall` takes a role name, never a model id. A per-critic `model` override in
#: config therefore reaches the wire as a per-critic role, `critic:brief`; when that role is not
#: registered the call falls back to the plain `critic` role rather than losing the critic.
CRITIC_ROLE = "critic"

#: The three critic templates, per critic name. FR-181 GLOBAL role templates, flat in `prompts/`.
CRITIC_TEMPLATES: dict[str, str] = {
    "brief": "critic_brief.md", "system": "critic_system.md", "craft": "critic_craft.md"}
#: The canned remedy sheet (FR-323). It resolves NOTHING — the sentences are SELECTED in code and
#: keyed by `(code, zone)`, exactly as `vision_check_question.md`'s carrier turn always was.
FIX_TEMPLATE = "gauntlet_fix.md"

# --------------------------------------------------------------------------------------------
# The vocabularies (spec §3, FROZEN). Each critic's enum is its own — the partition is what stops
# the craft critic reporting that a word is missing and the brief critic grading typography.
# --------------------------------------------------------------------------------------------

#: Contract fidelity + leakage. PRESENCE, never quality.
BRIEF_CODES: tuple[str, ...] = (
    "missing_text", "invented_text", "translated", "pair_break", "missing_mark", "forbidden_mark",
    "platform_chrome", "identity_leak", "counter_value", "signature")
#: Style contract + cross-frame consistency.
SYSTEM_CODES: tuple[str, ...] = (
    "style_palette", "style_layout", "style_consistency", "counter_placement")
#: Execution quality. EXECUTION, never content.
CRAFT_CODES: tuple[str, ...] = (
    "garbled", "truncated", "contrast", "logo_fidelity", "composition", "frame_integrity")
CRITIC_CODES: dict[str, tuple[str, ...]] = {
    "brief": BRIEF_CODES, "system": SYSTEM_CODES, "craft": CRAFT_CODES}
#: All twenty codes — the vocabulary `gauntlet_fix.md` is keyed by and validated against.
ALL_CODES: frozenset[str] = frozenset(BRIEF_CODES + SYSTEM_CODES + CRAFT_CODES)

#: FR-325 tier 1. These five block a deck outright, whatever `fail_action` says.
LEAKAGE_CODES: frozenset[str] = frozenset(
    {"identity_leak", "forbidden_mark", "platform_chrome", "invented_text", "translated"})
#: FR-325 tier 3 (Session 5.6/F7, operator ruling 2026-08-19): cross-frame counter TREATMENT is
#: cosmetic. gpt-image-2 oscillates the deck's own FR-313 position badge across re-renders — chip,
#: then plain, then missing — and a re-render fixing some other defect drops the badge as
#: collateral, so render-model churn was killing decks whose only standing defect was where that
#: badge sits and what it is drawn in. A wrong or missing counter VALUE is a different code
#: (`counter_value`, the brief critic's) and stays in tier 2: the number is contract content, its
#: styling is not. A cosmetic code is ordinary everywhere except the terminal policy — it is
#: judged, it enters `standing`, it fails its frame (`_fails`) and it buys re-render rounds; it
#: simply cannot be the reason a finished, fully paid-for deck goes unpublished.
COSMETIC_CODES: frozenset[str] = frozenset({"counter_placement"})
#: FR-325 tier 2 — everything the brief critic can say that is not leakage, plus every system code
#: that is not cosmetic. The vocabularies above stay frozen (spec §3); only this tier assignment
#: moved. Membership here is NECESSARY but not sufficient for a block since Session 5.7/F8: a
#: system code listed here is still demoted to the degrade bucket when the critic marked that
#: particular verdict `confidence: low` (`_lowconf_system`), and since Session 5.8/F9-A also when
#: the verdict was first heard on the last round about a frame no round re-rendered
#: (`_final_round_discovery`) — so the terminal partition is over DEFECTS, not over this set
#: alone. Brief codes here block at every confidence, and both demotions leave leakage untouched.
CONTRACT_CODES: frozenset[str] = (
    (frozenset(BRIEF_CODES) - LEAKAGE_CODES) | (frozenset(SYSTEM_CODES) - COSMETIC_CODES))

#: Where in the frame a defect sits. One closed set for all three critics (spec §3).
ZONES: tuple[str, ...] = (
    "top", "upper", "middle", "lower", "foot", "left", "right", "centre", "chip", "card",
    "full_frame")

_MAX_DEFECTS_PER_FRAME = 3
_MAX_DEFECTS_PER_CALL = 8
_DETAIL_MAX = 200
_EXPECTED_MAX = 2000  # one expected line, capped: a mapped panel is 1500 chars upstream (FR-304)
_MAX_REMEDIES = 3
_FIX_MAX_CHARS = 600
#: The newlines `fix_instruction`'s own `"\n".join` puts between the sections of a suffix that
#: carries at least one remedy line: header -> remedies, remedies -> blank, blank -> precedence,
#: precedence -> blank, blank -> closing. Counted rather than estimated, because `fix_reserve` is
#: only honest if it measures the assembly it reserves room for.
_FIX_JOIN_CHARS = 5
#: `PromptEngine.render(suffix=...)` separates the filled template from the suffix with a blank
#: line. Two characters, and they are the caller's to reserve: a reservation that forgets them
#: hands the body two characters more room than the provider will actually allow it.
_SUFFIX_SEPARATOR_CHARS = 2

_CARRIER = (
    "Return the verdict JSON for the {count} attached frame(s), in the order attached. "
    "The `frame` number in your answer is the ATTACHMENT position (1..{count}) — never a number "
    "drawn inside the picture.")

#: What a wordless-by-mandate frame's expected block says. The critics' templates name this literal
#: token, so the two must be read together (spec §3: "the picture cannot tell you which; the
#: contract can").
_NONE = "(none)"

#: Spec §3, VERBATIM: the conflict-precedence block every fix suffix carries. It is quoted here
#: because it is the part of the remedy channel that must never vary with the defect — the render
#: model needs the same tie-break rule every time — and because `gauntlet_fix.md` may not exist yet
#: on a given machine (FR-183's built-in absence during the v2.2.0 wave order).
PRECEDENCE_BLOCK = """Resolve these in order, and never by changing words:
1. Remove anything forbidden or not quoted in the TEXT block.
2. Render every quoted string in the TEXT block, in full, in its own language.
3. Fix legibility and fit by changing the LAYOUT — more lines, tighter leading,
   a wider block, the plate or card STYLE_DNA describes, a simpler ground.
4. Keep STYLE_DNA, the anchor's scene and the deck's palette unchanged.
Fix only the named defects; everything else stays as rendered, a quoted
position badge and every sanctioned mark included.
The quoted strings are locked. Shortening, re-wording, translating, ellipsing or
dropping any of them is a worse failure than the defect being fixed."""

#: Spec §3, VERBATIM: the fence-closing line every fix suffix ENDS with. Without it the FIX section
#: reads to a render model as one more block of renderable words.
FENCE_LINE = (
    "Everything in this FIX section describes a previous failure. It contains no words to render. "
    "The TEXT block above remains the only source of renderable words in this frame.")

_FIX_HEADER = "FIX — this is a re-render of a frame that failed review."

#: The STAND-IN emission order — a byte-copy of `gauntlet_fix.md`'s own `## ORDER` list, used only
#: when that file cannot be read (the sheet is authoritative whenever it can). It mirrors the
#: precedence block's four steps flattened onto the codes: remove first (a leaked identity or mark
#: is the expensive one), then the locked strings, then the style contract, then craft.
_PRECEDENCE: tuple[str, ...] = (
    "identity_leak", "platform_chrome", "forbidden_mark", "invented_text", "signature",
    "counter_value", "translated", "missing_text", "pair_break", "missing_mark",
    "style_palette", "style_layout", "style_consistency", "counter_placement",
    "contrast", "garbled", "truncated", "logo_fidelity", "composition", "frame_integrity",
)

#: The STAND-IN remedies (FR-323/FR-183). `prompts/gauntlet_fix.md` is the source of the canned
#: sentences; these are what ships when that file is missing, unreadable or half-edited, and they
#: are written in the sheet's OWN grammar so one selection path serves both: `{zone}` takes the
#: defect's zone with underscores replaced by spaces, `{chars}` an integer count, and a `[ … ]`
#: segment is dropped whole when its values are unavailable. One row per code, `*`-style (any
#: zone) — the file carries the zone-specific variants. Every sentence is REMOVAL-side or
#: LAYOUT-side: none of them asks the render model to change, shorten or translate a word, which
#: is the failure this whole channel exists to avoid.
_REMEDIES: dict[str, str] = {
    "missing_text": ("Render every string the TEXT block quotes, in full, in the {zone} area, "
                     "whole and legible; give a long one more lines, tighter leading or a wider "
                     "block."),
    "invented_text": ("The {zone} area carried lettering that the TEXT block does not quote"
                      "[ — about {chars} characters]; render no words there that the TEXT block "
                      "does not quote."),
    "translated": ("Render every quoted string in its own original language, character for "
                   "character; translate nothing."),
    "pair_break": ("Set the quoted lines as one column of rows in the {zone} area: each quoted "
                   "line keeps its own row, a label and its value stay together in it, and an "
                   "over-long row wraps under its own label."),
    "missing_mark": ("Draw every mark the TOOL MARKS line names as the real logo, in its true "
                     "brand colours, at icon size beside the row it belongs to."),
    "forbidden_mark": ("Draw no brand, company, competitor or platform logo or wordmark in the "
                       "{zone} area other than a mark the TOOL MARKS line names."),
    "platform_chrome": ("Draw no social-platform interface in the {zone} area: no watermark, "
                        "username, @handle, profile picture, follower, like, view or comment "
                        "counter, play button or progress bar."),
    "identity_leak": ("No person's name, @handle, profile picture, face or personal identity "
                      "appears anywhere in this frame; the {zone} area carries none."),
    "counter_value": ("When the TEXT block quotes a counter line, render it exactly as quoted, "
                      "once, in the {zone} area the COUNTER RULE names, and no other page number "
                      "or pip trail; when it quotes none, draw no badge."),
    "signature": ("Render the wordmark exactly as the TEXT block quotes it, once, in the {zone} "
                  "area, and no other signature or logotype anywhere in the frame."),
    "style_palette": ("Use only STYLE_DNA's own palette, ink, surface and light in the {zone} "
                      "area; a sanctioned tool mark keeps its true brand colours and is the only "
                      "exception."),
    "style_layout": ("Place the {zone} content in the zone and treatment the layout describes — "
                     "same plate, card, rule, alignment and margins."),
    "style_consistency": ("Match slide 1 of this deck exactly in the {zone} area: same typeface, "
                          "weight, scale and leading for the same role, same ground and surface, "
                          "same mark position."),
    "counter_placement": ("Put the position badge in the same place and the same chip treatment "
                          "as every other slide of this deck."),
    "garbled": ("Draw the {zone} lettering once, cleanly: well-formed letterforms with correct "
                "accents, no doubled, ghosted, overstruck or overlapping type, and no second copy "
                "of the same words."),
    "truncated": ("Keep the {zone} lettering whole inside the frame: hold every string within the "
                  "central 80% of the picture, clear of every edge, and size its box to the text "
                  "rather than clipping it."),
    "contrast": ("Make the {zone} lettering read at a glance on a phone: set it on the plate, "
                 "card or clear ground STYLE_DNA describes, at a size that survives thumbnail "
                 "scale."),
    "logo_fidelity": ("Draw the sanctioned tool mark exactly as the real logo is drawn — same "
                      "shapes, proportions, glyph and letterforms — with no redesign and no "
                      "invented substitute."),
    "composition": ("Give the {zone} element its own room: one text block and one focal element, "
                    "nothing overlapping or colliding, no duplicated subject, clear margins on "
                    "every side."),
    "frame_integrity": ("Compose natively for the frame this request sets and fill it edge to "
                        "edge: no letterbox or pillar bars, no seams or tiling repeats, no "
                        "stretching, and no crop of a larger composition."),
}

#: The sheet's optional segment: `[ … ]` is dropped WHOLE (brackets included) when the values
#: inside it are unavailable — in practice whenever no `{chars}` count was measured. Nested
#: brackets are not a case the format has, so the non-greedy single-level match is the format.
_OPTIONAL = re.compile(r"\[([^\[\]]*)\]")


# --------------------------------------------------------------------------------------------
# Frozen types (spec §1)
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FrameUnderTest:
    """One rendered frame as the gauntlet sees it: its slide number and where the bytes are."""

    number: int
    #: A local file OR a Kie result URL (the reel seed frame) — `vision_check.load_images`' union.
    source: Path | str


@dataclass(frozen=True, slots=True)
class RerenderResult:
    """What the caller's `RerenderFn` did with one fix request — the whole money seam's answer."""

    status: Literal["delivered", "declined_budget", "declined_deck_budget", "declined_runway",
                    "failed", "halted"]
    frame: FrameUnderTest | None = None
    cost_usd: float = 0.0


#: `(frame_number, fix_suffix) -> RerenderResult`. Implemented as a closure by the caller
#: (`_Deck`, `generate._one`, `reel`): it owns references, the reserve, the runway check, FR-317
#: exclusivity and pricing. The gauntlet knows none of that.
RerenderFn = Callable[[int, str], Awaitable[RerenderResult]]


@dataclass(frozen=True, slots=True)
class FrameContract:
    """What ONE frame was ordered to carry — the referent every verdict is judged against."""

    number: int
    body_lines: list[str] = field(default_factory=list)  # verbatim, in order; [] == wordless
    #: "" | "empty_panel" | "over_sanity_ceiling" | "handle_or_url" — why it is wordless.
    wordless_reason: str = ""
    #: FR-304c: this panel's source text may already have been cut off. A trailing "…" is CONTENT.
    truncation_suspect: bool = False
    counter: str = ""  # "" when the deck has no counter
    signature: str = ""  # "" except a signed anchor (the wordmark text)
    is_list: bool = False  # list/table frame -> FR-329 pair integrity applies


@dataclass(frozen=True, slots=True)
class DeckContract:
    """The deck-wide half of the referent: marks, forbidden strings, style, platform."""

    frames: list[FrameContract] = field(default_factory=list)
    required_marks: list[str] = field(default_factory=list)  # FR-315/FR-330 REQUIRED side
    #: Creator identity forms, competitor names, unsanctioned brand marks, §0.12 flag names.
    forbidden_terms: list[str] = field(default_factory=list)
    style_dna: str = ""
    layout_zones: str = ""
    list_mode: str = ""  # flattened prose, "" when the style has no list treatment
    sanctioned_illegible: str = ""  # what this style deliberately renders unreadable
    platform: str = ""

    def frame(self, number: int) -> FrameContract:
        """This frame's contract; an unlisted frame gets an empty one rather than an exception."""
        return next((f for f in self.frames if f.number == number), FrameContract(number=number))


@dataclass(frozen=True, slots=True)
class Defect:
    """One critic's finding about one frame. `detail` never leaves the report/events (FR-323)."""

    code: str
    zone: str = ""
    confidence: Literal["high", "low"] = "high"
    detail: str = ""


@dataclass(frozen=True, slots=True)
class FrameDefects:
    """One frame's defects from ONE critic. An empty tuple is a pass."""

    frame: int  # the SLIDE number, already re-mapped from the attachment slot
    defects: tuple[Defect, ...] = ()


@dataclass(frozen=True, slots=True)
class RoundVerdict:
    """What one round saw: every critic's per-frame defects, and who was dropped."""

    round: int
    per_critic: dict[str, list[FrameDefects]]
    unavailable: tuple[str, ...] = ()
    #: The frames this round actually re-rendered. Not in spec §1's field list; spec §6's
    #: `meta.yaml.gauntlet.rounds[].rerendered` needs it and nothing else carries it.
    rerendered: tuple[int, ...] = ()

    def failed_frames(self) -> tuple[int, ...]:
        """Frames with at least one FAILING defect this round, ascending (craft-low excluded)."""
        return tuple(sorted({d.frame for rows in self.per_critic.values() for d in rows
                             if any(_fails(defect) for defect in d.defects)}))


@dataclass(slots=True)
class GauntletReport:
    """One deck's (or one frame's) whole gauntlet: the verdict, the rounds, the money."""

    result: Literal["pass", "blocked", "degraded", "budget_stop", "deadline_stop", "skipped"]
    rounds: list[RoundVerdict] = field(default_factory=list)
    rerenders: int = 0
    rerender_cost_usd: float = 0.0  # summed from RerenderResult.cost_usd
    critic_cost_usd: float = 0.0
    #: The deck SHIPPED but the gate is not a clean pass, and the asset says so: every consumer
    #: hangs `GAUNTLET_DEGRADED` on this one flag. Four causes reach it — a critic was dropped as
    #: unavailable (D3, the gate was thinner than configured), FR-325's cosmetic tier let a
    #: standing `counter_placement` ship (Session 5.6/F7), F8 demoted a standing low-confidence
    #: system verdict (Session 5.7), or F9-A graced a defect first heard on the last round about a
    #: frame the run never re-rendered (Session 5.8). `result` tells the dropped-critic case from
    #: the other three: only the demotions are `"degraded"`, and which of them it was is read off
    #: the standing codes and the round history in `rounds` (the console forks on the dropped set
    #: alone, `runner._gauntlet_lines`).
    degraded_gate: bool = False
    #: FR-325 tier 3, and the reason this flag exists rather than a fourth `result` value: a
    #: craft-ONLY standing failure is a SUCCESS carrying a `GAUNTLET_CRAFT` tag (spec §2). The
    #: `result` therefore stays `"pass"` and the standing craft defects are visible in
    #: `rounds[-1]`; a caller tags the asset off this flag. `cfg.craft_blocks: true` overrides it
    #: to `blocked`, in which case this stays False because the craft defects were terminal.
    craft_only: bool = False

    @property
    def shipped(self) -> bool:
        """True when the asset may be published — everything except `blocked`."""
        return self.result != "blocked"


# --------------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------------


async def run_deck(
    frames: Sequence[FrameUnderTest],
    contract: DeckContract,
    rerender: RerenderFn,
    *,
    cfg: GauntletConfig,
    call: StructuredCall,
    log: Any = None,
    engine: PromptEngine | None = None,
) -> GauntletReport:
    """Judge a whole deck, re-render what fails, up to `cfg.rounds_max` rounds (spec §2).

    Args:
        frames: the finished frames at NATIVE resolution, in deck order. One call per critic per
            round covers all of them — N slides never cost N critic calls.
        contract: what the deck was ordered to be. `contract.frames` carries one row per slide.
        rerender: the caller's money seam — `(frame_number, fix_suffix) -> RerenderResult`. Every
            budget, runway and reference decision lives inside it.
        cfg: `run.gauntlet` — rounds, per-deck budget, fail action, which critics are on.
        call: `llm.structured_call` (`models.StructuredCall`), on the `critic` role.
        log: anything with `.event(...)` / `.warn(...)`; may be None.
        engine: the run's `PromptEngine` (a niche pack's `prompts_dir` overrides live on it).
            Defaults to a plain engine over `prompts/`. Not in spec §1's signature, which named no
            template source at all; the critics' prompts are files, so one is needed.

    Returns:
        A `GauntletReport`. Never raises: an unusable critic degrades the gate, an unusable panel
        skips it, and a caller that gets `result == "blocked"` is the only one that must not ship.
    """
    return await _Run(list(frames), contract, rerender, cfg, call, log,
                      engine or PromptEngine(log=log), _rounds_max(cfg, deck=True)).go()


async def run_single(
    frame: FrameUnderTest,
    contract: DeckContract,
    rerender: RerenderFn,
    *,
    cfg: GauntletConfig,
    call: StructuredCall,
    log: Any = None,
    engine: PromptEngine | None = None,
) -> GauntletReport:
    """Judge ONE frame — a standalone image, a reel seed frame, or the carousel anchor pre-gate.

    Same loop, same critics, same terminal policy; the only differences are that there is no
    cross-frame consistency to judge and that the round ceiling is the lower of `rounds_max` and
    `rounds_max_image` (spec §4: a lone frame that needs three rounds is a copy problem). The
    anchor pre-gate reaches this with `replace(cfg, rounds_max=2, rounds_max_image=2,
    critics=(brief, craft))` (FR-324's one extra round, Session 5.5/F3), so taking the
    MINIMUM is what honours both that call and the standalone-image ceiling.

    `contract` is a `DeckContract` as for a deck; it may carry just this frame's row (extra rows
    are ignored — only the judged frame's block is ever sent).
    """
    return await _Run([frame], contract, rerender, cfg, call, log,
                      engine or PromptEngine(log=log), _rounds_max(cfg, deck=False)).go()


def fix_instruction(
    frame: FrameContract | int,
    defects: Sequence[Defect | str],
    *,
    contract: DeckContract | None = None,
    engine: PromptEngine | None = None,
    invented_chars: int | None = None,
    log: Any = None,
) -> str:
    """The guarded fix channel (FR-323): canned remedies for a frame's STANDING defects.

    A critic's own words never appear here. Each defect selects a canned sentence out of
    `prompts/gauntlet_fix.md` by `(code, zone)` — `zone` from the closed enum, nothing else — and
    the assembled block is fence-neutralised, swept with `topic_filter.apply_blocklist` and
    identity-stripped against `contract.forbidden_terms` before it is handed back. The
    `invented_text` remedy may cite a character count and a zone and nothing else: the string that
    was invented is exactly what must never be repeated into a render payload.

    Args:
        frame: the frame's contract (or just its number — the number is only used for logging).
        defects: the UNION of that frame's standing defects across every round so far, so round 3
            never undoes round 2's remedy. Plain code strings are accepted and read as zoneless.
        contract: the deck contract, for the forbidden-term sweep. Optional; omitting it skips
            only the sweep, never the neutralisation.
        engine: the run's `PromptEngine`, which resolves `gauntlet_fix.md`. When the sheet is
            absent or unreadable the built-in remedies stand in (FR-183 shape) — never a raise.
        invented_chars: how many characters of invented lettering were seen, when the caller has a
            count. It is the ONLY number the sheet's optional `[ … ]` segments carry; with no
            count those segments are dropped whole, brackets and all.
        log: for the `gauntlet_fix_truncated` event.

    Returns:
        The suffix to append to the re-render's prompt: header, remedies, the sheet's precedence
        block, and its fence-closing line — capped at 3 remedies / 600 characters of remedy text.
    """
    number = frame.number if isinstance(frame, FrameContract) else int(frame)
    sheet = _sheet(engine)
    seen: dict[str, str] = {}  # code -> zone (the FIRST zone seen wins; a code is remedied once)
    for item in defects:
        code = item.code if isinstance(item, Defect) else str(item)
        zone = item.zone if isinstance(item, Defect) else ""
        if code in ALL_CODES and code not in seen:
            # A defect with no usable zone is read as `full_frame`: "somewhere in this frame" is
            # the honest reading, and it is the zone the sheet's own zone-less phrasing is under.
            seen[code] = zone if zone in ZONES else "full_frame"
    ordered = [code for code in sheet.order if code in seen]
    ordered += [code for code in seen if code not in sheet.order]  # never silently drop a code
    lines: list[str] = []
    dropped = max(0, len(ordered) - _MAX_REMEDIES)  # over the 3-remedy cap
    for code in ordered[:_MAX_REMEDIES]:
        line = f"- {sheet.remedy(code, seen[code], chars=invented_chars)}"
        if sum(len(existing) + 1 for existing in lines) + len(line) > _FIX_MAX_CHARS:
            dropped += 1  # over the 600-character cap
            continue
        lines.append(line)
    if dropped > 0:
        _emit(log, "gauntlet_fix_truncated", level="warn",
              message=f"frame {number}: {dropped} fix remedy/remedies dropped "
                      f"(cap {_MAX_REMEDIES} remedies / {_FIX_MAX_CHARS} chars)",
              frame=number, kept=len(lines), dropped=dropped, codes=list(ordered),
              sheet=sheet.origin)
    body = "\n".join([_FIX_HEADER, *lines, "", sheet.precedence, "", sheet.closing])
    return _sanitised(body, contract)


def fix_reserve(engine: PromptEngine | None = None) -> int:
    """The MOST characters a fix suffix can ever add to a render prompt, separator included.

    What it is for (F1-C). A render prompt is assembled against the provider's character wall, and
    `PromptEngine.render(suffix=...)` counts the suffix inside that wall — so a re-render's BODY
    gets `cap - len(suffix)` where a first render got `cap`. The 2026-08-14 live run paid for that
    twice over: every fix round rendered with 924–1,248 characters less rulebook than the round it
    was fixing, the tail the assembler drops is the CONSTRAINTS back half, and a loop that judges
    round 2 against rules round 2 never received oscillates rather than converges. A caller that
    reserves this figure on EVERY pass gives both passes the same body room, and the fix rides in
    the space that was already held back for it.

    Why the sheet is asked rather than a constant returned. `prompts/gauntlet_fix.md` is
    operator-overridable (FR-183) and only its REMEDIES are capped — the precedence block and the
    closing fence are emitted verbatim at whatever length the sheet writes them. A hard-coded
    number would describe the shipped sheet and quietly under-reserve for an edited one, which is
    the same defect one indirection later. The built-in sheet answers when no engine is passed or
    the file cannot be read, exactly as `fix_instruction` assembles from it.

    Args:
        engine: the run's `PromptEngine`, which resolves `gauntlet_fix.md`. `None` (a unit test, a
            caller with no run in scope) measures the built-in sheet.

    Returns:
        Characters to hold back from a prompt's character cap for the fix channel: the header, the
        600-character remedy allowance, the sheet's own precedence and closing texts, the newlines
        `fix_instruction` joins them with, and the blank line the engine puts before the suffix.
        Never a raise — an unreadable sheet is the FR-183 case, not an error.
    """
    sheet = _sheet(engine)
    return (len(_FIX_HEADER) + _FIX_MAX_CHARS + len(sheet.precedence) + len(sheet.closing)
            + _FIX_JOIN_CHARS + _SUFFIX_SEPARATOR_CHARS)


# --------------------------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------------------------


class _Run:
    """One gauntlet execution. Holds the mutable frame set, the standing defects and the report.

    Kept as a class rather than a pile of parameters because every stage needs the same six
    collaborators and the same three pieces of state; the public API stays two functions.
    """

    def __init__(self, frames: list[FrameUnderTest], contract: DeckContract,
                 rerender: RerenderFn, cfg: GauntletConfig, call: StructuredCall, log: Any,
                 engine: PromptEngine, rounds_max: int) -> None:
        self.frames = {f.number: f for f in frames}
        self.order = [f.number for f in frames]
        self.contract = contract
        self.rerender = rerender
        self.cfg = cfg
        self.call = call
        self.log = log
        self.engine = engine
        self.rounds_max = rounds_max
        self.report = GauntletReport(result="pass")
        #: frame -> code -> defect, accumulated across ALL rounds (the fix channel's referent).
        self.standing: dict[int, dict[str, Defect]] = {}
        #: frame -> the defects the MOST RECENT round that judged it found (the terminal referent).
        self.latest: dict[int, list[Defect]] = {}
        self.dropped: set[str] = set()  # critics dropped for the whole deck

    async def go(self) -> GauntletReport:
        """Run the rounds and settle the terminal policy. The one entry point."""
        enabled = self._enabled()
        if not self.frames or not enabled or self.rounds_max < 1:
            self.report.result = "skipped"
            _emit(self.log, "gauntlet_round", level="warn",
                  message="gauntlet did not run (no frames, no enabled critic, or zero rounds)",
                  frames=len(self.frames), critics=list(enabled), rounds_max=self.rounds_max)
            return self.report
        scoped: list[int] = list(self.order)  # what brief & craft judge this round
        for index in range(1, self.rounds_max + 1):
            verdict = await self._round(index, scoped)
            self.report.rounds.append(verdict)
            if not (survivors := [name for name in self._enabled() if name not in self.dropped]):
                self.report.result = "skipped"
                _emit(self.log, "gauntlet_critic_unavailable", level="warn",
                      message="every critic was unavailable — the deck ships unjudged",
                      round=index, unavailable=sorted(self.dropped))
                return self.report
            fails = verdict.failed_frames()
            _emit(self.log, "gauntlet_round", message=self._round_line(index, verdict, fails),
                  round=index, rounds_max=self.rounds_max, critics=survivors,
                  unavailable=list(verdict.unavailable), failed_frames=list(fails),
                  defects=_defect_rows(verdict))
            if not fails:
                self.report.result = "pass"
                return self.report
            if index == self.rounds_max:
                break
            stop, rerendered = await self._rerender_all(index, fails)
            self.report.rounds[-1] = replace(verdict, rerendered=tuple(rerendered))
            if stop:
                return self._terminal(stop)
            if not rerendered:  # nothing moved; another round would judge the same pixels
                break
            scoped = rerendered
        return self._terminal(None)

    # ----------------------------------------------------------------- one round

    async def _round(self, index: int, scoped: Sequence[int]) -> RoundVerdict:
        """Every surviving critic, concurrently, against its own frame scope (FR-324)."""
        names = [name for name in self._enabled() if name not in self.dropped]
        # `system` ALWAYS judges every frame: a fixed slide can break the deck's consistency, and
        # only a cross-frame reader can see that. brief & craft judge round 1 in full and then only
        # what was re-rendered — which is where most of the round-2/3 critic spend is saved.
        scopes = {name: (self.order if (name == "system" or index == 1) else list(scoped))
                  for name in names}
        outcomes = await asyncio.gather(
            *(self._critic(name, scopes[name], index) for name in names))
        per_critic: dict[str, list[FrameDefects]] = {}
        unavailable: list[str] = []
        for name, outcome in zip(names, outcomes):
            self.report.critic_cost_usd += outcome.cost_usd
            if outcome.rows is None:
                unavailable.append(name)
                self.dropped.add(name)
                self.report.degraded_gate = True
                _emit(self.log, "gauntlet_critic_unavailable", level="warn",
                      message=f"critic {name} dropped for this deck: {outcome.reason}",
                      critic=name, round=index, reason=outcome.reason)
                continue
            per_critic[name] = outcome.rows
        self._absorb(per_critic, {frame for scope in scopes.values() for frame in scope})
        return RoundVerdict(round=index, per_critic=per_critic, unavailable=tuple(unavailable))

    def _absorb(self, per_critic: Mapping[str, list[FrameDefects]], judged: set[int]) -> None:
        """Fold this round's verdicts into `latest` (terminal) and `standing` (the fix channel)."""
        for frame in judged:
            self.latest[frame] = []
        for rows in per_critic.values():
            for row in rows:
                self.latest.setdefault(row.frame, []).extend(row.defects)
                bucket = self.standing.setdefault(row.frame, {})
                for defect in row.defects:
                    if _fails(defect):
                        bucket.setdefault(defect.code, defect)

    async def _critic(self, name: str, scope: Sequence[int], index: int) -> _Outcome:
        """One critic, one multi-image call, one round. Never raises — see `_Outcome.rows`."""
        frames = [self.frames[number] for number in scope if number in self.frames]
        if not frames:
            return _Outcome(rows=[], cost_usd=0.0)
        blobs, positions = await vision_check.load_images([f.source for f in frames], self.log)
        if not blobs:
            return _Outcome(rows=None, reason="no frame could be read")
        numbers = [frames[position - 1].number for position in positions]
        try:
            system = self.engine.render(CRITIC_TEMPLATES[name], _context(name, self.contract,
                                                                         numbers))
        except (ValueError, LookupError) as exc:  # unresolved placeholder / no template at all
            return _Outcome(rows=None, reason=f"critic prompt unusable: {exc}"[:_DETAIL_MAX])
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": _CARRIER.format(count=len(blobs))}]
        result = await self._invoke(name, messages, _schema(name), blobs)
        cost = float(getattr(result, "cost_usd", 0.0) or 0.0)
        if getattr(result, "degraded", False) or not isinstance(result.parsed, Mapping):
            reason = (getattr(result, "reason", "") or getattr(result, "raw_text", "")
                      or "critic returned nothing usable")
            return _Outcome(rows=None, cost_usd=cost, reason=str(reason)[:_DETAIL_MAX])
        return _Outcome(rows=self._parse(name, result.parsed, numbers, index), cost_usd=cost)

    async def _invoke(self, name: str, messages: list[dict[str, Any]],
                      schema: dict[str, Any], blobs: list[bytes]) -> Any:
        """The LLM seam. A per-critic model override rides its own role; an unregistered one
        falls back to the shared `critic` role rather than costing the deck a critic."""
        role = _critic_role(name, self.cfg)
        try:
            return await self.call(role, messages, schema, blobs)
        except ValueError:
            if role == CRITIC_ROLE:
                raise
            _emit(self.log, "gauntlet_critic_unavailable", level="warn",
                  message=f"LLM role {role} is not registered; critic {name} used {CRITIC_ROLE}",
                  critic=name, role=role)
            return await self.call(CRITIC_ROLE, messages, schema, blobs)

    def _parse(self, name: str, parsed: Mapping[str, Any], numbers: Sequence[int],
               index: int) -> list[FrameDefects]:
        """Model rows -> `FrameDefects`, attachment slots re-mapped onto slide numbers.

        The remap reuses `vision_check.load_images`' `positions` contract exactly (spec §2): the
        verdict's `frame` is a 1-based ATTACHMENT slot, and a dropped unreadable frame must never
        shift a verdict onto its neighbour.
        """
        codes = frozenset(CRITIC_CODES[name])
        rows: list[FrameDefects] = []
        budget = _MAX_DEFECTS_PER_CALL
        for order, row in enumerate(parsed.get("frames") or [], start=1):
            if not isinstance(row, Mapping):
                continue
            try:
                slot = int(row.get("frame") or order)
            except (TypeError, ValueError):
                slot = order
            if not 1 <= slot <= len(numbers):
                continue
            defects: list[Defect] = []
            for entry in list(row.get("defects") or [])[:_MAX_DEFECTS_PER_FRAME]:
                if budget <= 0:
                    break
                if not isinstance(entry, Mapping) or str(entry.get("code")) not in codes:
                    continue
                zone = str(entry.get("zone") or "")
                defects.append(Defect(
                    code=str(entry["code"]),
                    zone=zone if zone in ZONES else "",
                    confidence="low" if str(entry.get("confidence")) == "low" else "high",
                    detail=str(entry.get("detail") or "")[:_DETAIL_MAX]))
                budget -= 1
            if not defects and row.get("pass") is False:
                # A "fail" with nothing to fix cannot be re-rendered against; it would burn a round
                # and a dollar on a frame nobody named a defect in. Logged, then read as a PASS.
                _emit(self.log, "critic_empty_fail", level="warn",
                      message=f"critic {name} failed frame {numbers[slot - 1]} with no defects "
                              "— read as a pass",
                      critic=name, frame=numbers[slot - 1], round=index)
            rows.append(FrameDefects(frame=numbers[slot - 1], defects=tuple(defects)))
        return rows

    # ----------------------------------------------------------------- re-render

    async def _rerender_all(self, index: int,
                            fails: Sequence[int]) -> tuple[str | None, list[int]]:
        """Re-render every failing frame concurrently; return `(stop_result, replaced_frames)`."""
        suffixes = {number: fix_instruction(self.contract.frame(number),
                                            list(self.standing.get(number, {}).values()),
                                            contract=self.contract, engine=self.engine,
                                            log=self.log)
                    for number in fails}
        results = await asyncio.gather(
            *(self.rerender(number, suffixes[number]) for number in fails),
            return_exceptions=True)
        stop: str | None = None
        replaced: list[int] = []
        for number, result in zip(fails, results):
            if isinstance(result, BaseException):  # a caller-side crash is a failed frame, not ours
                _emit(self.log, "gauntlet_rerender", level="error",
                      message=f"re-render of frame {number} raised "
                              f"{type(result).__name__} — the frame stays failed",
                      frame=number, round=index)
                continue
            self.report.rerender_cost_usd += float(result.cost_usd or 0.0)
            _emit(self.log, "gauntlet_rerender",
                  message=f"frame {number}: re-render {result.status}",
                  frame=number, round=index, status=result.status, cost_usd=result.cost_usd,
                  codes=sorted(self.standing.get(number, {})))
            if result.status == "delivered" and result.frame is not None:
                self.frames[result.frame.number] = result.frame
                self.report.rerenders += 1
                replaced.append(result.frame.number)
            elif result.status in ("declined_budget", "declined_deck_budget"):
                stop = stop or "budget_stop"
            elif result.status in ("declined_runway", "halted"):
                stop = stop or "deadline_stop"
            # "failed": the frame keeps its standing defects into the terminal policy.
        if stop:
            _emit(self.log, f"gauntlet_{stop}", level="warn",
                  message=f"gauntlet stopped after round {index}: {stop}",
                  round=index, frames=list(fails), rerenders=self.report.rerenders,
                  rerender_cost_usd=round(self.report.rerender_cost_usd, 4))
        return stop, replaced

    # ----------------------------------------------------------------- terminal

    def _terminal(self, stop: str | None) -> GauntletReport:
        """FR-325's four tiers, applied to whatever is still standing (spec §2).

        A `stop` (budget or deadline) is reported as itself EXCEPT when a leakage defect is
        standing: that tier "always blocks", and a run that ran out of money with a competitor's
        logo on a slide must not ship it. Spec §2 and §7 are read together here — §7's "terminal
        per tier policy" wins on the leakage tier, §2's mapped stop result wins otherwise.

        The tiers settle in this order: **leakage** always blocks; a **stop** reports itself;
        **contract** follows `fail_action`; **craft** blocks only where `cfg.craft_blocks` asked
        it to; the **degrade bucket** degrades whatever `fail_action` says; and a craft-only
        standing set passes, tagged. The degrade tier sits BELOW the `craft_blocks` branch so an
        operator who asked for craft to block still gets a block when a craft defect stands beside
        a demoted one, and ABOVE the craft-only pass so a demoted defect keeps its degrade when a
        craft opinion merely rides along. `craft_blocks` also asks whether a craft code is actually
        standing: before the cosmetic tier existed, reaching that branch could only mean craft, and
        a demoted-only set must not be blocked by a knob about execution quality.

        The degrade bucket has THREE members, and each is a different reason the same finished deck
        should ship tagged rather than die:

        1. **cosmetic** — the code is in `COSMETIC_CODES` (Session 5.6/F7: the render model's own
           position-badge churn is not a defect an operator can spend their way out of);
        2. **low-confidence system** — the system critic hedged its own verdict (Session 5.7/F8,
           `_lowconf_system`: a critic that says it is not sure is not a reason to bin a deck);
        3. **final-round discovery** — a run of two or more rounds ended with a defect nobody had
           said before the last round, on a frame nobody re-rendered all run (Session 5.8/F9-A,
           `_final_round_discovery`: FR-324's loop never got to try). Asked of tier-2 codes only:
           the grace exists to stop a BLOCK, and a craft or cosmetic defect was already shipping
           without it. A single-round run is out of scope entirely — nothing was denied a fix
           round where no fix round existed.

        All three are decided per DEFECT rather than per code, which is why `contract_standing` and
        `degrade_standing` are built from `(frame, defect)` pairs rather than from a code set: the
        same `style_consistency` can be a sure verdict on slide 2 and a hedge — or a last-round
        surprise — on slide 4, and a code SET would have to pick one bucket for both. All three are
        terminal-only: `_fails` is untouched, so every one of these defects still fails its frame,
        still enters `standing`, still appears on the round line and still buys its re-render
        rounds with the canned remedy attached (the craft critic's low-confidence rule is the
        OTHER, stronger one — it suppresses the failure outright). And none of them touches
        leakage, which blocks from any bucket at any confidence in any round.
        """
        standing = [(frame, defect) for frame, defects in self.latest.items()
                    for defect in defects if _fails(defect)]
        codes = {defect.code for _frame, defect in standing}
        if not codes:
            self.report.result = stop or "pass"
            return self.report
        # F9-A's grace is asked ONLY of tier-2 defects, because it exists to stop a block and
        # nothing else can be stopped: a craft opinion already ships as a tagged PASS
        # (`craft_only`) and a cosmetic code already ships as a degrade, so gracing either would
        # make a deck that was going to ship read WORSE than it is — a craft-only set would land
        # in the degrade branch below and lose its `GAUNTLET_CRAFT` tag to a `GAUNTLET_DEGRADED`
        # one. The predicate itself stays a statement about WHEN the defect was heard; which tiers
        # it is asked about belongs here, beside the partition it moves a defect across.
        graced = {(frame, defect.code) for frame, defect in standing
                  if defect.code in CONTRACT_CODES
                  and _final_round_discovery(frame, defect, self.report.rounds)}
        contract_standing = {defect.code for frame, defect in standing
                             if defect.code in CONTRACT_CODES and not _lowconf_system(defect)
                             and (frame, defect.code) not in graced}
        degrade_standing = {defect.code for frame, defect in standing
                            if defect.code in COSMETIC_CODES or _lowconf_system(defect)
                            or (frame, defect.code) in graced}
        if codes & LEAKAGE_CODES:
            self.report.result = "blocked"
        elif stop:
            self.report.result = stop  # type: ignore[assignment]
        elif contract_standing:
            self.report.result = "blocked" if self.cfg.fail_action == "block" else "degraded"
        elif self.cfg.craft_blocks and codes.intersection(CRAFT_CODES):
            self.report.result = "blocked"
        elif degrade_standing:
            # Tier 3: cosmetic (Session 5.6/F7), a demoted low-confidence system verdict
            # (Session 5.7/F8) or a final-round discovery on a never-re-rendered frame
            # (Session 5.8/F9-A). The `fail_action: degrade` outcome exactly — the deck SHIPS and
            # says so. `degraded_gate` is the flag every consumer already reads to hang
            # `GAUNTLET_DEGRADED` on the asset (`generate/carousel.py`, `generate/__init__.py`,
            # `generate/reel.py`), so this cannot ship as a silent clean pass; the standing
            # defects stay readable in `rounds[-1]` beside it, with their confidence.
            self.report.result = "degraded"
            self.report.degraded_gate = True
            # No terminal event fires here, deliberately: `40-outputs` FR-80 and `20-integrations`
            # FR-328 enumerate a CLOSED gauntlet event catalog, and neither this degrade nor the
            # older `fail_action: degrade` one has an event in it. What the round already logged
            # (`gauntlet_round`: the failed frames and their codes) plus `meta.yaml.gauntlet`
            # (`result: degraded`, `degraded_gate: true`) is the record; a new event type would be
            # code ahead of the PRD.
        else:
            # Tier 4: craft-only. A SUCCESS carrying the GAUNTLET_CRAFT tag — the standing craft
            # defects stay readable in `rounds[-1]`, which is what the report and gallery show.
            self.report.result = "pass"
            self.report.craft_only = True
        if self.report.result == "blocked":
            _emit(self.log, "gauntlet_blocked", level="error",
                  message=f"deck BLOCKED after {len(self.report.rounds)} round(s): "
                          f"{', '.join(sorted(codes))}",
                  codes=sorted(codes), rounds=len(self.report.rounds),
                  frames=sorted(frame for frame, defects in self.latest.items()
                                if any(_fails(d) for d in defects)),
                  # Which tier actually killed the deck. `craft` is reachable only under
                  # `cfg.craft_blocks`, and it used to be mislabelled `contract` here; `cosmetic`
                  # is not reachable at all, because that tier degrades rather than blocks (a
                  # cosmetic code standing beside a craft one under `craft_blocks` blocks on the
                  # CRAFT knob, which is what this field then says). The catalog stays the three
                  # values `leakage | contract | craft`: nothing in the degrade bucket — cosmetic,
                  # hedged or graced — can reach this event on its own, and the field reads
                  # `contract_standing` rather than the raw code set so that a deck blocked on the
                  # craft knob WHILE a demoted code stands is not relabelled `contract` by a code
                  # that did not block.
                  tier=("leakage" if codes & LEAKAGE_CODES else
                        "contract" if contract_standing else "craft"), stop=stop or "")
        return self.report

    # ----------------------------------------------------------------- helpers

    def _enabled(self) -> list[str]:
        """The configured critics that are on, in a stable order (brief, system, craft)."""
        critics = getattr(self.cfg, "critics", {}) or {}
        return [name for name in ("brief", "system", "craft")
                if getattr(critics.get(name), "enabled", False)]

    def _round_line(self, index: int, verdict: RoundVerdict, fails: Sequence[int]) -> str:
        """The FR-296 console sentence: what this round saw, in one line."""
        if not fails:
            return f"round {index}/{self.rounds_max} — all {len(self.frames)} frame(s) passed"
        detail = "; ".join(
            f"{name}: " + ", ".join(sorted({f"{d.code} s{row.frame}" for row in rows
                                            for d in row.defects if _fails(d)}))
            for name, rows in verdict.per_critic.items()
            if any(_fails(d) for row in rows for d in row.defects))
        return (f"round {index}/{self.rounds_max} — {len(fails)} frame(s) failed ({detail})"
                + (f" — re-rendering {len(fails)}" if index < self.rounds_max else ""))


@dataclass(frozen=True, slots=True)
class _Outcome:
    """One critic call's answer. `rows=None` is the unavailable state — never an exception."""

    rows: list[FrameDefects] | None = None
    cost_usd: float = 0.0
    reason: str = ""


# --------------------------------------------------------------------------------------------
# Internals — contract rendering, schema, sanitisation
# --------------------------------------------------------------------------------------------


def _rounds_max(cfg: GauntletConfig, *, deck: bool) -> int:
    """Rounds ceiling: `rounds_max` for a deck, `min(rounds_max, rounds_max_image)` for one frame."""
    rounds = max(0, int(getattr(cfg, "rounds_max", 1)))
    if deck:
        return rounds
    return min(rounds, max(0, int(getattr(cfg, "rounds_max_image", rounds))))


def _critic_role(name: str, cfg: GauntletConfig) -> str:
    """`critic` by default; `critic:<name>` when this critic carries its own model override."""
    critic = (getattr(cfg, "critics", {}) or {}).get(name)
    return f"{CRITIC_ROLE}:{name}" if getattr(critic, "model", None) else CRITIC_ROLE


def _fails(defect: Defect) -> bool:
    """Whether a defect FAILS its frame. A low-confidence craft opinion is recorded, never fatal.

    Deliberately NOT confidence-aware for the system critic (Session 5.7/F8): a low-confidence
    system verdict fails its frame like any other, which is what keeps it in `standing`, on the
    round line and in the fix suffix that buys it a re-render. Only `_terminal` reads its
    confidence, and only to decide whether it may kill the deck at the end.
    """
    return not (defect.confidence == "low" and defect.code in CRAFT_CODES)


def _lowconf_system(defect: Defect) -> bool:
    """Whether a STANDING defect is a system verdict the terminal policy demotes (FR-325, F8).

    Operator ruling 2026-08-19, on canary #2 (`output/20260819_181930_8e6d`): a fully rendered,
    fully paid-for deck went unpublished on ONE `style_consistency` verdict that the system critic
    itself marked `confidence: low` — a micro-placement opinion about where a mark sat, on a deck
    the same critic had cleared on palette, layout and counter, and after F7 had removed every
    counter defect. A critic that says it is not sure is not a reason to bin a finished deck; it
    is a reason to ship it tagged, so the operator can look and decide.

    The demotion is deliberately narrower than the craft critic's low-confidence rule in two ways.
    It is SYSTEM-ONLY — a low-confidence brief verdict is still about contract CONTENT (a missing
    string, a leaked identity, the wrong counter value), where an uncertain critic is exactly the
    one worth stopping for. And it is TERMINAL-ONLY — the craft rule suppresses the failure itself
    (`_fails`), so a low-confidence craft opinion never fails a frame and never buys a re-render,
    whereas this one leaves the whole loop intact: the defect fails its frame, enters `standing`,
    is named on the round line and spends its fix rounds with the canned remedy attached. Only the
    last word changes. `counter_placement` reaches the same degrade at EVERY confidence
    (`COSMETIC_CODES`); this is the confidence-keyed door beside that code-keyed one.
    """
    return defect.confidence == "low" and defect.code in SYSTEM_CODES


def _final_round_discovery(frame: int, defect: Defect, rounds: Sequence[RoundVerdict]) -> bool:
    """Whether a STANDING defect was heard too late to be fixed (FR-325, Session 5.8/F9-A).

    Operator ruling 2026-08-19, on canary #3 (`output/20260819_191734_0jc2`): a seven-slide deck
    was blocked by a high-confidence `style_consistency` verdict on FRAME 4 — a frame that had
    passed rounds 1 and 2 cleanly and that no round ever re-rendered. The critic only saw it in
    round 3, when the round budget was spent and there was nothing left to buy: the fix loop
    FR-324 describes (round 1 finds, round 2 fixes, round 3 checks the fix) never ran for that
    defect at all. The deck died on a verdict it was structurally denied the chance to answer.
    Re-rendering siblings toward each other moves the consistency baseline, so the LAST round is
    exactly where a cross-frame reader is most likely to name a frame for the first time.

    The four conditions, all of which must hold, and each of which is doing its own work:

    0. **The run actually had a fix-round structure** — it judged at least TWO rounds (conductor
       ruling 2026-08-19, Session 5.8/W1). A run that ends on round 1 has no earlier round to have
       heard anything and no delivered re-render to point at, so conditions 1 and 2 below are
       vacuously true and EVERY tier-2 defect would be graced. That is not the asymmetry this rule
       is about. `rounds_max_image: 1` ships as the default for standalone images and reel seed
       frames precisely because "a lone frame that needs three rounds is a copy problem" (spec §4),
       and an operator who sets `rounds_max: 1` on a deck is asking for a judge-only gate; neither
       may be silently turned into report-only. The grace answers the MULTI-ROUND discovery
       asymmetry — a frame the loop kept passing over while it re-rendered its siblings — and
       where no loop ran there is no asymmetry to answer.
    1. **The frame was never re-rendered this run** — `frame` appears in no round's `rerendered`
       list. A frame that WAS re-rendered has had money and a canned remedy spent on it; whatever
       is still wrong with it survived a fix attempt rather than missing one.
    2. **The `(frame, code)` pair was never raised before the final round.** The pair, not the
       code: the same `style_consistency` naming slides 2 and 3 in round 1 says nothing about
       slide 4, whereas the same pair standing since round 1 means the loop DID have its chance —
       it re-rendered, or it declined to, and either way the defect is not a discovery. A sighting
       counts even where it did not fail its frame (a `confidence: low` craft opinion is still the
       critic having said it out loud): the question is whether the defect is NEWS, not whether it
       was fatal when it was first heard.
    3. **The code is not leakage.** Defensive rather than load-bearing (every `LEAKAGE_CODES`
       member is a brief-critic code, and by FR-324's round scoping brief judges only re-rendered
       frames from round 2 on, so a leaked identity on a virgin frame in round 3 cannot arise),
       but the rule that a name, a face or a competitor's mark never ships is not one to leave
       standing on an argument about scoping.

    That same round scoping makes this de-facto SYSTEM-only in practice: from round 2 the brief and
    craft critics see only the frames that were re-rendered, so the only critic that can name an
    untouched frame late is the one that always reads the whole deck. It is written generally
    anyway — the scoping is FR-324's, not this predicate's, and a future round policy must not
    silently widen a carve-out written to assume it.

    Like the two demotions beside it (`COSMETIC_CODES`, `_lowconf_system`) this is TERMINAL-ONLY,
    though here by nature rather than by rule: `_terminal` runs when the run is over, so there is
    no re-render left for the grace to suppress. `_fails` never consults it.

    `_terminal` asks this only about `CONTRACT_CODES` defects — the tier that would otherwise
    block. A craft defect is already a shipped, tagged pass and a cosmetic one already a shipped
    degrade, so gracing either could only make a surviving deck's verdict read worse. That
    narrowing lives at the call site, with the tier partition it belongs to; this predicate stays
    a statement about WHEN a defect was heard and about nothing else.

    Args:
        frame: the slide the defect stands on. `Defect` carries no frame of its own — the round
            history keys defects by frame (`FrameDefects`) and so does `_Run.latest`, so the caller
            passes the number it already has rather than this predicate re-deriving it.
        defect: the standing defect, read for its code alone (confidence is the OTHER door).
        rounds: every round this run judged, in order — `self.report.rounds`, which already carries
            both halves of the history: `per_critic` for what was said, `rerendered` for what was
            paid for. Nothing had to be threaded in for this; `rounds[-1]` is the final round by
            construction, because `_terminal` is only ever reached after the last round appended,
            and its LENGTH is what condition 0 reads — one round means no fix structure ran.

    Returns:
        True when the defect joins the degrade bucket instead of deciding a block.
    """
    if defect.code in LEAKAGE_CODES or len(rounds) < 2:
        return False
    if any(frame in verdict.rerendered for verdict in rounds):
        return False
    return not any(row.frame == frame and any(seen.code == defect.code for seen in row.defects)
                   for verdict in rounds[:-1]
                   for rows in verdict.per_critic.values() for row in rows)


def _context(name: str, contract: DeckContract, numbers: Sequence[int]) -> dict[str, str]:
    """The critic's whole world: contract data only — no render prompt, no prior verdicts.

    Every value is a plain string keyed by a name from `models.CRITIC_PLACEHOLDERS`, and the
    returned dict is NARROWED to that critic's own `prompts_engine` allowlist. The narrowing is
    belt AND braces on purpose: the allowlist already makes an out-of-role name unresolvable
    (FR-260/261), and this makes the value not exist in the first place, so no override template
    and no future edit can hand the leakage critic a competitor-free style block it was never
    meant to reason about. An unknown role (no allowlist row) gets the full map rather than an
    empty one — that is a wiring bug, and an unresolved-placeholder error names it far better
    than a prompt full of blanks would.
    """
    values = {
        "expected_blocks": _expected_blocks(contract, numbers),
        "required_marks": ", ".join(m for m in contract.required_marks if str(m).strip()) or _NONE,
        "forbidden_terms": ", ".join(t for t in contract.forbidden_terms if str(t).strip())
                           or _NONE,
        "style_dna": contract.style_dna,
        "layout_zones": contract.layout_zones,
        "list_mode": contract.list_mode,
        "sanctioned_illegible": contract.sanctioned_illegible,
        "platform": contract.platform,
    }
    allowed = allowlist(CRITIC_TEMPLATES.get(name, ""))
    return {key: value for key, value in values.items() if key in allowed} if allowed else values


def _expected_blocks(contract: DeckContract, numbers: Sequence[int]) -> str:
    """The enumerated per-frame line blocks — the referent for `missing_text`/`invented_text`.

    Rows are keyed by ATTACHMENT slot (what the critic answers in) with the slide number beside
    it (what the operator reads), so the two numbering systems never have to be inferred. A frame
    that is wordless BY MANDATE says `(none)` and names why, which is the one thing a picture
    cannot tell a critic: an empty frame and a frame whose words failed to render look identical.
    """
    blocks: list[str] = []
    for slot, number in enumerate(numbers, start=1):
        frame = contract.frame(number)
        rows = [f"frame {slot} (slide {number}):"]
        lines = [line for line in frame.body_lines if str(line).strip()]
        if lines:
            rows += [f'  L{i}: "{str(line)[:_EXPECTED_MAX]}"' for i, line in enumerate(lines, 1)]
        else:
            reason = f" ({frame.wordless_reason})" if frame.wordless_reason else ""
            rows.append(f"  {_NONE} — wordless by mandate{reason}")
        rows.append(f'  counter: "{frame.counter}"' if frame.counter else f"  counter: {_NONE}")
        rows.append(f'  signature: "{frame.signature}"' if frame.signature
                    else f"  signature: {_NONE}")
        if frame.is_list:
            rows.append("  list frame: label/value pairs must stay together (FR-329)")
        if frame.truncation_suspect:
            rows.append("  truncation suspected in the SOURCE text: a trailing ellipsis here is "
                        "content, not a rendering defect")
        blocks.append("\n".join(rows))
    return "\n\n".join(blocks)


def _schema(name: str) -> dict[str, Any]:
    """One critic's strict schema — its OWN enum, required everywhere, no extra properties.

    Mirrors `vision_check._SCHEMA`'s conventions (RESULTS.md §E). The per-critic enum is the
    mechanical half of the presence/execution partition: the craft critic literally cannot emit
    `missing_text`, and the brief critic cannot emit `contrast`.
    """
    defect = {
        "type": "object",
        "properties": {"code": {"type": "string", "enum": list(CRITIC_CODES[name])},
                       "zone": {"type": "string", "enum": list(ZONES)},
                       "confidence": {"type": "string", "enum": ["high", "low"]},
                       "detail": {"type": "string", "maxLength": _DETAIL_MAX}},
        "required": ["code", "zone", "confidence", "detail"],
        "additionalProperties": False,
    }
    frame = {
        "type": "object",
        "properties": {"frame": {"type": "integer"}, "pass": {"type": "boolean"},
                       "defects": {"type": "array", "items": defect,
                                   "maxItems": _MAX_DEFECTS_PER_FRAME}},
        "required": ["frame", "pass", "defects"],
        "additionalProperties": False,
    }
    return {"name": f"gauntlet_{name}",
            "schema": {"type": "object", "properties": {"frames": {"type": "array",
                                                                   "items": frame}},
                       "required": ["frames"], "additionalProperties": False}}


@dataclass(frozen=True, slots=True)
class _Sheet:
    """`prompts/gauntlet_fix.md`, parsed: the four sections the remedy channel is assembled from.

    `remedies` is keyed `(code, zone)` with `""` standing for the sheet's `*` (any-zone) row, which
    every code carries — so selection never fails and no defect can reach a render payload with no
    canned sentence to stand for it.
    """

    precedence: str
    order: tuple[str, ...]
    remedies: dict[tuple[str, str], str]
    closing: str
    origin: str  # the sheet's own origin, or "built-in" — logged, never rendered

    def remedy(self, code: str, zone: str, *, chars: int | None = None) -> str:
        """The canned sentence for one defect: exact-zone row first, then the code's `*` row.

        The two substitutions are the sheet's own (documented in its header): `{zone}` takes the
        zone token with underscores replaced by spaces, `{chars}` an integer count. A bracketed
        `[ … ]` segment is dropped WHOLE when its values are unavailable — which is every call
        with no `chars`, the brackets included, so no square bracket ever reaches a payload.
        """
        sentence = (self.remedies.get((code, zone)) or self.remedies.get((code, ""))
                    or _REMEDIES.get(code, ""))
        sentence = (_OPTIONAL.sub(lambda m: m.group(1), sentence) if chars is not None
                    else _OPTIONAL.sub("", sentence))
        return (sentence.replace("{zone}", zone.replace("_", " "))
                        .replace("{chars}", str(chars if chars is not None else "")))


#: The FR-183 stand-in: the module's own remedies under the same four-section contract. It is what
#: `fix_instruction` assembles from when no engine is passed at all (a unit test, a caller with no
#: run in scope) and when `prompts/gauntlet_fix.md` cannot be read or parsed.
_BUILT_IN_SHEET = _Sheet(precedence=PRECEDENCE_BLOCK, order=_PRECEDENCE,
                         remedies={(code, ""): text for code, text in _REMEDIES.items()},
                         closing=FENCE_LINE, origin="built-in")


def _sheet(engine: PromptEngine | None) -> _Sheet:
    """The remedy sheet in force. The FILE is the source; the built-ins stand in when it is gone.

    Parsing is exactly what `gauntlet_fix.md`'s own header specifies: four sections opened at
    column 0 by `## PRECEDENCE`, `## ORDER`, `## REMEDIES`, `## CLOSING`; the precedence and
    closing texts are emitted verbatim; ORDER is one comma-separated list of codes in emission
    precedence; REMEDIES are `code | zone | sentence` rows. Unknown codes and malformed rows are
    ignored rather than fatal, and any section that comes back empty falls back to its built-in
    twin — a half-edited sheet degrades to the shipped wording instead of emitting a blank fix.
    Never raises: an unreadable sheet is exactly the FR-183 case.
    """
    if engine is None:
        return _BUILT_IN_SHEET
    try:
        template = engine.template(FIX_TEMPLATE)
    except (LookupError, OSError, ValueError):
        return _BUILT_IN_SHEET
    sections: dict[str, list[str]] = {}
    current = ""
    for line in template.text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().upper()
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    remedies: dict[tuple[str, str], str] = {}
    for row in sections.get("REMEDIES", []):
        parts = [part.strip() for part in row.split("|")]
        if len(parts) == 3 and parts[0] in ALL_CODES and (parts[1] == "*" or parts[1] in ZONES):
            remedies[(parts[0], "" if parts[1] == "*" else parts[1])] = parts[2]
    order = tuple(code for code in
                  (token.strip() for token in " ".join(sections.get("ORDER", [])).split(","))
                  if code in ALL_CODES)
    return _Sheet(
        precedence=_block(sections.get("PRECEDENCE", [])) or PRECEDENCE_BLOCK,
        order=order or _PRECEDENCE,
        remedies=remedies or dict(_BUILT_IN_SHEET.remedies),
        closing=_block(sections.get("CLOSING", [])) or FENCE_LINE,
        origin=template.origin if remedies else f"{template.origin} (unparseable; built-ins)",
    )


def _block(lines: Sequence[str]) -> str:
    """One section's text as the sheet wrote it — inner shape kept, outer blank lines dropped."""
    kept = list(lines)
    while kept and not kept[0].strip():
        kept.pop(0)
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept)


def _sanitised(text: str, contract: DeckContract | None) -> str:
    """Everything the fix channel owes before a render payload may see it (FR-323).

    Fence-neutralise (FR-102), sweep the forbidden terms with the same word-boundary blocklist the
    caption path uses, then take the near-miss creator forms out with `fuzzy_strip`. The canned
    sentences contain none of those strings today; that is exactly why the sweep is cheap to keep
    and why it must not depend on the canned text staying canned — an overridden `gauntlet_fix.md`
    is operator-authored, and this is the boundary that makes that safe.
    """
    out = _fence_safe(text)
    terms = [str(term) for term in (contract.forbidden_terms if contract else []) if str(term)]
    if terms:
        out = apply_blocklist(out, terms)
        out, _hits = fuzzy_strip(out, terms)
    return out


def _defect_rows(verdict: RoundVerdict) -> list[dict[str, Any]]:
    """The round's defects as flat rows for `events.jsonl` (D30: full detail, events only)."""
    return [{"critic": name, "frame": row.frame, "code": defect.code, "zone": defect.zone,
             "confidence": defect.confidence, "detail": defect.detail}
            for name, rows in verdict.per_critic.items() for row in rows
            for defect in row.defects]


def _emit(log: Any, event_type: str, message: str = "", *, level: str = "info",
          **data: Any) -> None:
    """One event, both files, never a raise — the log is optional everywhere in this module."""
    getattr(logger, "warning" if level in ("warn", "error") else "info")(
        "%s: %s", event_type, message)
    if log is None:
        return
    try:
        log.event(event_type, message, level=level, **data)
    except (AttributeError, TypeError):  # a duck-typed log with only `.warn(...)`
        warn = getattr(log, "warn", None)
        if callable(warn):
            warn(event_type, message, **data)


__all__ = [
    "BRIEF_CODES", "CONTRACT_CODES", "COSMETIC_CODES", "CRAFT_CODES", "CRITIC_CODES",
    "CRITIC_ROLE",
    "CRITIC_TEMPLATES", "DeckContract", "Defect", "FENCE_LINE", "FIX_TEMPLATE", "FrameContract",
    "FrameDefects", "FrameUnderTest", "GauntletReport", "LEAKAGE_CODES", "PRECEDENCE_BLOCK",
    "RerenderFn", "RerenderResult", "RoundVerdict", "SYSTEM_CODES", "ZONES", "fix_instruction",
    "fix_reserve", "run_deck", "run_single",
]
