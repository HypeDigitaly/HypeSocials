"""CAROUSEL — one deck, anchored: slide 1 first and checked, slides 2–N template-locked.

Module contract
---------------
Purpose: turn ONE approved carousel plan entry into a folder of slide files and one terminal
`meta.yaml`. Owns the FR-95 anchor chain, the gauntlet ordering around it, the per-slide FR-97
moderation fallback and the honest partial-deck packaging — nothing else. Money, the profile
lookup and the FR-203 ledger lines belong to the `submit` callable the caller passes in: this
module never prices a job, never touches `env.budget` and never calls `render.run`.

Public API: `render_carousel(entry, env, folder, *, submit) -> AssetRecord` · `Submit`.

Invariants:
- **The deck is the SOURCE deck** (FR-304/§0.4′, v2.1.0). Its length was fixed at ASSIGN from the
  bound slideshow post's panel count — clamped to the platform ceiling, priced at the Confirm gate
  — and this module renders exactly that many slides, mapping our slide *i* onto their panel *i*.
  Copy no longer decides the length, and a panel that carried no words renders WITHOUT on-image
  text: the pre-D46 fallback repeated the headline into every unwritten slot, which turned a
  source deck's empty panel into a second printing of slide 1's line.
- **The anchor is judged BEFORE slides 2–N are submitted, and gets ONE round to fix itself**
  (FR-95/FR-324, D49). Slide 1 is a chained artifact — every other slide copies it — so a garbled
  headline found afterwards is found N renders too late. The pre-gate is one `gauntlet.run_single`
  call with the `brief` + `craft` critics only (spec §1: there is no separate anchor entry point,
  and `system` has no cross-frame consistency to judge on a deck of one) and FR-324's ceiling of
  "one extra round of re-renders, on the deck budget" — judge, fix once, judge again. Its re-render
  is discretionary (FR-106c); a declined or failed one ships the flagged anchor, and the deck
  anchors to the FINAL slide 1. The pre-gate never blocks: the whole deck faces the full panel
  afterwards, and blocking a deck on a two-critic reading of its cover would refuse decks the fix
  loop can fix.
- **`{{style_dna}}` is built ONCE per deck and is byte-identical in every slide's context**
  (FR-189/M9) — a deck reads as one deck through templating, never through a consistency check
  (FR-20 explicitly has none). Cover-vs-body divergence lives in the assigned style's
  `per_format_guidance` instead: slide 1 renders under its `carousel_cover` prose and slides 2–N
  under `carousel_slide`, appended to `{{render_prompt}}` — the one block a deck is ALLOWED to
  vary, because the anchor is a cover and the rest are pages.
- **The cover may be bought more than once, and exactly one of them is committed** (FR-351,
  v2.6.0/D62). At `run.cover_candidates: 2..3` slide 1 is submitted that many times CONCURRENTLY
  with a byte-identical prompt — the candidates differ only by the provider's sampling, because a
  perturbed prompt would make them incomparable — and one metered `analysis` call ranks the landed
  ones against the style contract the deck was ordered under. The winner becomes `slide_01` and
  `anchor_url`; every landed candidate's bytes are kept under `covers/` and named in
  `meta.yaml.cover_pick` so the operator can see what was turned down. It is fail-open end to end:
  no metered call means the extras are never ordered at all (renders nobody can judge are waste), a
  failed or unusable pick commits candidate 1 and tags `cover_pick_degraded`, and a candidate that
  never landed is a WARNING rather than a missing slide — D51 is about a slide that can never come,
  and slide 1 came. `cover_candidates: 1` is the pre-D62 path byte for byte.
- **A dead anchor buys ONE more anchor before the deck is unchained** (FR-95, v2.2.0). An
  unchained deck is the defect the anchor exists to prevent, and one extra cover render against a
  deck of five to nine is the cheapest repair there is; the Confirm gate prices it (the anchor
  contingency is two units, FR-107). Only if the replacement also dies do all N slides render
  independently. Both the replacement and the fallback burst are PRE-COMMITTED work
  (FR-95/FR-106b): cap bookkeeping must never be the thing that splits a deck.
- **A partial deck ships when the RUN stopped; it does not when the RENDER failed** (FR-20/10 §10,
  as amended by D51). Delivered slides stay, `missing_slide_numbers` names the rest 1-indexed and
  the asset is tagged `incomplete` — for losses to a halt, the deadline, a runway refusal,
  exhausted credits or a full disk. But a slide permanently lost to a render DEFECT (terminal
  after FR-317, and after FR-95's replacement for the anchor) makes the deck unsalvageable: our
  slide *i* is their panel *i* (FR-304), so nothing further is ordered for it, it is tagged
  `deck_viability_loss` and it is not published. Jobs already submitted are NEVER cancelled — they
  are billed, they land, and they are recorded (FR-29/FR-203). Zero slides delivered is a failed
  creative that KEEPS its paid caption (FR-74).
- **Nothing is ordered the clock cannot pay for** (D51). The runway gate lives in the injected
  `submit`, so this module sees a refusal rather than a failure: it is unbilled, it carries no
  taskId, it never joins `self.outcomes` and it never burns FR-317's one-shot.
- **Nothing raises.** `render.KieOutOfCredits` latches `env.credits_exhausted` and the deck is
  packaged as it stands (FR-167); `env.halted` is re-read before EVERY submission, so Ctrl+C and
  the deadline stop ordering mid-deck rather than mid-run (FR-201/108).

- **The deck faces the GAUNTLET, and the gauntlet owns the loop** (D49, FR-322–330, v2.2.0). Three
  fresh-context critics judge the frames that came back against contract data, failing frames
  re-render with a CANNED fix suffix, and the whole thing repeats up to `rounds_max` times. This
  module supplies exactly two things: the contract (`generate/contracts.py`) and the `RerenderFn`
  closure. That closure is the MONEY SEAM and it owns every dollar decision in the loop — the
  discretionary reserve against the run cap, the per-deck `gauntlet.deck_budget_usd`, D51's runway
  check, and FR-317 exclusivity (a gauntlet re-render is a FRESH submission with its own ledger
  rows; it is never itself resubmitted and never gets a second poll window). `gauntlet.py` prices
  nothing and never sees `env.budget`.
- **A gauntlet re-render that never happens loses NOTHING.** The slide it was improving is already
  on disk and already shipping, so a decline, a halt or a failure is logged and never joins the
  deck's missing-slide ledger (`_note(lost=False)`) — `missing_slide_numbers` means "not delivered".
- **A BLOCKED deck keeps every paid artifact and is not published** (FR-325/FR-74). A standing
  leakage defect blocks whatever `fail_action` says; a contract defect blocks under `block`; a
  craft-only failure SHIPS with a `GAUNTLET_CRAFT` tag. `packager.block()` is the writer, the run
  exits 1, and the deck's source post is NOT burnt in the history window.
- **The deck counts itself the way its SOURCE did, or not at all** (D-D, v2.1.2). The counting
  convention is detected ONCE per deck from the source's chrome (padding, separator, `// ` prefix)
  and re-based onto OUR length, so a five-slide deck cut from a nine-panel source reads "3/5" and
  never "3/9". Unlike the wordmark it rides EVERY slide — a badge on the cover alone is a typo,
  not a signature — and a deck with no detected convention passes an empty string, which is what
  makes the template's "this deck carries no slide counter" branch fire.
- **A sanctioned mark is the one real logo a slide may draw** (D-A, v2.1.2). The marks come from
  the source slide's own `brand_marks`, minus every configured competitor, the source author's own
  identity and anything chrome-shaped (@handles, watermarks, platform names) — what survives is the
  product logo the panel was ABOUT. The same names ride the vision check, or the check flags the
  logo we deliberately ordered as fake UI.
- **A sanctioned mark rides as PIXELS wherever pixels exist** (FR-315, v2.1.3/D48). A name alone
  buys an invention: "Higgsfield", "Flodesk" and "Murf" come back as confident, wrong logos. So the
  deck crops each detected mark out of the source slide ONCE, uploads it once (the run memo), and
  attaches it per slide as a MARK PATCH reference with a copy-it-exactly role line. Everything
  about it is fail-open (FR-315d): no boxes, no stored slide, a failed crop or a failed upload each
  cost that mark its pixels and nothing else — it still renders from its name and the template's
  written description, and the slide is never blocked.
- **One automatic resubmit per slide, and only for the failures a resubmit can fix** (FR-317,
  v2.1.3/D48). A slide whose job TIMED OUT or failed for a non-moderation reason is submitted
  again, exactly once, as discretionary spend; a second failure is final and the slide joins the
  missing ledger. Its one-shot ledger is SEPARATE from the vision retry's (NFR-4) — a slide may
  legitimately use both — and the timed-out attempt reconciles at $0, so the resubmit costs one
  render, not two.
- **Every judged slide travels with the words it was ordered to carry** (FR-322, v2.2.0), and the
  fix loop may never touch them (FR-304 carve-out): the `brief` critic's question is "are the
  quoted strings there, in full, in their own language, and is anything else readable?", and the
  fix suffix is REMOVAL-side and LAYOUT-side only. The 2026-08-13 audit shipped a slide of invented
  copy that read clean and legible, which is the whole reason the gate looks at the contract rather
  than at the picture alone.

Do not: call `render.run`, reserve or reconcile money, compute a price, write a ledger line, name
a Kie field, put a critic's own words in a render prompt, or import `hypesocials.generate` at
runtime — that package imports this module.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from hypesocials import gauntlet, render
# FR-351 (v2.6.0/D62): the cover best-of-N judge. Imported as a MODULE, never as `pick`, for two
# reasons — the call site then reads `cover_pick.pick(...)`, which says which question is being
# asked, and the seam stays patchable in one place. Mind the near-collision with `_Deck.cover_pick`
# below: that attribute is this deck's RECEIPT (the dict that reaches `meta.yaml`), while the bare
# name is always the module. They never appear in the same expression.
from hypesocials import cover_pick
from hypesocials.models import (
    AssetRecord, CopySet, DegradationTag, MetaStyle, PlanEntry, PlanEntryStatus, RenderFailCause,
    RenderOutcome, RenderOutcomeKind, RenderParams, RenderPriority, RenderRefs, SourcePost,
)
from hypesocials.outputs import AssetFolder, PackagingError
# `plan.py` owns the source-deck arithmetic (it is the stage that fixed this deck's length), so the
# truncation test below asks it rather than re-deriving "how long was the source deck" here — two
# implementations of that question are two decks that can disagree about which panels shipped.
from hypesocials.plan import source_panel_count
# D-D (v2.1.2): the source deck's counting convention is READ by the module that read the source
# deck. Detection lives beside the chrome transcription it parses, and this module holds the one
# CounterSpec per deck — two implementations of "did they number their slides" would be two decks
# that disagree about whether ours carries a badge.
from hypesocials.sources.slide_intel import CounterSpec, detect_counter
# FR-315 (D48): the mark's own pixels. `crop_marks` is SYNCHRONOUS (Pillow + file I/O) and runs
# off-thread here; it is the only Pillow user in the tree and it writes exclusively into the
# post's own `source/<post_id>/marks/` folder, which is the one path `refs.upload_local` will
# upload out of the source store (FR-244's amended carve-out).
from hypesocials.sources.logo_crops import crop_marks
# FR-315's two normalizers, shared (v2.2.0). They were private here until `logo_crops` and
# `slide_intel` needed the same two spellings of a mark; `logo_crops.py:112` collapsing the RAW
# name while this module collapsed the PEELED one is how deck 06 lost a patch it had already paid
# to upload. One definition, in the domain the strings come from.
from hypesocials.sources.mark_names import collapse, mark_name
# FR-351: the cover candidates' own bytes, at native resolution. The SAME loader the gauntlet's
# critics use (`vision_check.load_images`) — one frame loader in the product, so "a frame is never
# downscaled" and "an unreadable input is DROPPED, never shifted" hold for the cover pick without a
# second implementation of either. Its `positions` return is what maps a fetched blob back onto the
# candidate id it was submitted under when one of the downloads fails.
from hypesocials.vision_check import load_images
from hypesocials.generate.refs import (
    Reference, attach, branding_block, role_lines, style_of, upload_local, wordmark,
)
# D49: "what was this frame ORDERED to be" — built once for the deck, the standalone image and the
# reel seed frame alike, so three call sites cannot disagree about one style's own contract.
from hypesocials.generate import contracts
# FR-98 (v2.1.4): the delivered slide's real pixel size, read from its own header bytes. A sibling
# module rather than `hypesocials.generate`, which imports THIS one (see the "do not" list above).
from hypesocials.generate.pixels import native_size
from hypesocials.prompts_engine import (
    MissingTemplateError, UnresolvedPlaceholderError, build_context, style_dna,
)

if TYPE_CHECKING:  # a runtime import would be circular: generate/__init__.py imports this module
    from hypesocials.generate import Env

#: FR-181's per-profile render set. The anchor block is its own file so the template-lock wording
#: can be tuned without touching the slide scaffold (D24).
ROLE_SLIDE = "carousel_slide.md"
ROLE_ANCHOR = "carousel_anchor_instruction.md"

#: `per_format_guidance` keys, by slide role (§1.3's reserved keys): slide 1 is the deck's cover,
#: every other slide is a body page. M9 puts the cover/body divergence HERE precisely so
#: `{{style_dna}}` can stay byte-identical across the deck.
GUIDANCE_COVER = "carousel_cover"
GUIDANCE_SLIDE = "carousel_slide"
#: The role line the chained anchor carries until `carousel_anchor_instruction.md` replaces it
#: (FR-190) — never rendered as-is in a live deck, but never a blank line either.
_ANCHOR_ROLE = ("the finished slide 1 of this deck: reproduce its template, palette, typography "
                "and margins exactly")
#: FR-323/FR-18 (v2.2.0): the role line of a re-render's nearest delivered neighbour. It says what
#: the picture is FOR and, at least as importantly, what it is not for — a body page carries body
#: copy, and a re-render told only "match this" is being invited to copy the words too.
_NEIGHBOUR_ROLE = (
    "the finished slide {number} of this same deck — the page nearest this one that is already "
    "rendered. Match its template, palette, typography, margins, spacing and graphic language "
    "exactly, so this slide sits inside the deck rather than beside it. Take NOTHING else from it: "
    "not its words, not its subject, not its imagery. The text for THIS slide is the one given "
    "below and no other.")

#: FR-351: the sub-folder every fanned-out cover candidate is kept in, winner included. A folder
#: rather than a name prefix so the deck's own `slide_*` glob — the one the gallery and the
#: packager both walk — cannot pick a rejected cover up and show it as a delivered slide.
COVERS_DIR = "covers"
#: FR-351's file stem inside `COVERS_DIR`, formatted with the candidate's 1-based submission id.
#: The id is preserved through a failure (a deck whose candidate 2 died keeps `1` and `3`), so a
#: file name, a `cover_candidate_lost` log line and `meta.yaml`'s `chosen` all name the same render.
COVER_CANDIDATE_STEM = "cover_candidate"

ReserveKind = Literal["projected", "precommitted", "discretionary"]  # FR-106 a/b/c

#: F1-C: the blank line `PromptEngine.render(suffix=...)` puts between a filled template and its
#: suffix (`tail = f"\n\n{suffix}"`). Two characters, counted here because `_prompt_cap` hands the
#: suffix's room back and `gauntlet.fix_reserve` holds the same two aside — the reservation and the
#: refund have to describe the same string or the body budget moves between passes after all.
_SUFFIX_SEPARATOR = 2

_CREDITS = "kie_credits_exhausted — top up your Kie.ai credits (FR-167)"
_FALLBACK_SLIDES = 5
#: FR-325 tier 3: a deck whose ONLY standing failures are craft opinions ships, tagged. Resolved off
#: `DegradationTag` when that enum carries the member and spelled literally until then — exactly
#: like `PANELS_TRUNCATED` below: `AssetFolder.mark` stores whatever it is given and `DegradationTag`
#: is a `str` enum, so the bytes in `meta.yaml` are identical either way.
GAUNTLET_CRAFT = getattr(DegradationTag, "GAUNTLET_CRAFT", "gauntlet_craft")
#: The gate degraded because a critic could not be parsed and was dropped for the whole deck
#: (spec §2). The deck SHIPS — a broken checker never blocks delivery (D3) — and says so.
GAUNTLET_DEGRADED = getattr(DegradationTag, "GAUNTLET_DEGRADED", "gauntlet_degraded")
#: FR-73's `panels_truncated` (§0.4′): the source deck was longer than the platform ceiling, so it
#: ships as its first N panels with the indices preserved. Resolved off `DegradationTag` when that
#: enum carries the member and spelled literally until then — `models.py` belongs to another task
#: this wave, `AssetFolder.mark` stores whatever it is given, and `DegradationTag` is a `str` enum,
#: so the bytes in `meta.yaml` are identical either way.
PANELS_TRUNCATED = getattr(DegradationTag, "PANELS_TRUNCATED", "panels_truncated")
#: D51's `deck_viability_loss` (v2.2.0): ONE slide was permanently lost to a render defect, so the
#: deck was stopped rather than finished — the badge that separates "we stopped buying" from
#: `incomplete`, which means "this partial deck ships". Resolved off `DegradationTag` when that
#: enum carries the member and spelled literally until then, exactly like `PANELS_TRUNCATED` above:
#: `models.py` belongs to another task this wave, `AssetFolder.skip` stores whatever it is given,
#: and `DegradationTag` is a `str` enum, so the bytes in `meta.yaml` are identical either way.
DECK_VIABILITY_LOSS = getattr(DegradationTag, "DECK_VIABILITY_LOSS", "deck_viability_loss")

#: D-A: how many of a panel's named marks are even considered, and how many may be sanctioned onto
#: one slide. A panel showing nine real logos is an icon grid, and telling the render model to draw
#: nine real marks faithfully is how it draws nine invented ones.
#: D51's per-slide line for work the viability gate refused to order. One sentence, no cause: the
#: cause belongs to the slide that actually died and is logged once, on the deck.
_UNSALVAGEABLE = ("not ordered — a slide of this deck was permanently lost to a render defect, so "
                  "the deck can never be whole and nothing further was bought for it (D51)")

_MAX_MARKS_READ = 10
_MAX_MARKS = 4
#: What is never sanctioned, however the panel showed it: the creator's signature and the
#: platform's own furniture. Every render template bans platform UI outright, so a "TikTok
#: watermark" on this line would put two instructions in the same prompt at war.
_CHROME_WORDS = ("watermark", "handle", "username", "user name", "profile", "avatar", "follow",
                 "swipe", "tiktok", "instagram", "facebook", "youtube", "snapchat", "linkedin",
                 "pinterest", "threads", "twitter", "reddit", "whatsapp", "telegram")

#: FR-315: how many cropped MARK PATCH references one slide may carry. Four is `_MAX_MARKS` —
#: a slide never sanctions more marks than that, so it can never want more patches — and the
#: anchor keeps its own slot ahead of them inside the profile's 16-reference ceiling.
_MAX_MARK_PATCHES = _MAX_MARKS
#: FR-315's role line, in the REFERENCES vocabulary `carousel_slide.md` already speaks: that
#: template introduces "a MARK PATCH as the exact pixels of a sanctioned tool logo" and tells the
#: model the patch wins over its own memory of the mark. This sentence is that contract at the
#: attachment, so a logged prompt says which image is which without cross-reading the scaffold.
_MARK_PATCH_ROLE = (
    "MARK PATCH: the exact '{name}' mark, cropped from the source slide it appeared on. Copy this "
    "mark pixel-faithfully — true brand colours, exact glyph and proportions, no redesign, no "
    "re-lettering, no invented substitute. It contributes NOTHING else: not layout, not palette, "
    "not typography, not background, and none of the words around it.")

#: FR-316: sentence boundaries in a visual brief. The brief is model-written English prose, so a
#: full stop, a question mark or an exclamation mark followed by space is the whole grammar needed
#: to drop ONE sentence that names the creator without discarding the rest of the directive.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
#: Below this an author identifier is too short to match on: a two-character handle collapsed into
#: a sentence would hit half the English language and scrub briefs that never named anyone.
_MIN_AUTHOR_IDENT = 4


def _is_chrome(raw: str) -> bool:
    """True for a mark that is the creator's or the platform's furniture, not a product logo."""
    folded = str(raw or "").casefold()
    return "@" in folded or any(word in folded for word in _CHROME_WORDS)


class Submit(Protocol):
    """The caller's metered submission door — the ONLY way this module spends anything.

    It owns the FR-106 a/b/c reservation kinds, the profile lookup and the FR-203 ledger lines.
    `None` comes back only for `kind="discretionary"` when the cap declined the reservation
    (FR-106c); `render.KieOutOfCredits` is the one exception it may raise (FR-167).
    """

    async def __call__(
        self, entry: PlanEntry, params: RenderParams, refs: RenderRefs, *,
        job: Literal["image", "slide", "seed_frame", "clip"], priority: RenderPriority,
        kind: ReserveKind, label: str,
    ) -> RenderOutcome | None: ...


async def render_carousel(
    entry: PlanEntry, env: Env, folder: AssetFolder, *, submit: Submit
) -> AssetRecord:
    """Build one carousel deck and leave it terminal on disk. Never raises.

    `entry` is a PENDING carousel entry; `folder` already holds its `pending` meta and its paid
    caption. Returns the terminal record — `success` (whole or `incomplete`) or `failed` with a
    one-line `skip_reason` and every paid artifact intact (FR-74).
    """
    deck = _Deck(entry, env, folder, submit)
    await deck.build()
    return deck.package()


@dataclass(slots=True)
class _Deck:
    """State for one carousel: what was ordered, what landed, and what the check said."""

    entry: PlanEntry
    env: Env
    folder: AssetFolder
    submit: Submit
    texts: list[str] = field(default_factory=list)  # one line per slide, deck order (FR-13)
    dna: str = ""  # FR-189 — built once, reused byte for byte
    style: MetaStyle | None = None  # the assigned house style; None under an override brief (M14)
    branding: str = ""  # FR-292's colour/letterform block, or "" when this deck is unsigned
    wordmark: str = ""  # B1's TEXT-block brand name — slide 1's alone (M12), "" when unbranded
    #: D-D: the SOURCE deck's counting convention, detected once, or None for an uncounted deck.
    counter: CounterSpec | None = None
    attached: list[Reference] = field(default_factory=list)  # style + brief, role-labelled
    #: FR-315: collapsed mark name -> the Kie URL of its cropped patch. Built once per deck, keyed
    #: the way `_sanctioned_marks` spells a mark so the two lists join without a second cleaner.
    #: A mark absent from here is not a failure — it renders from its name (FR-315d).
    patches: dict[str, str] = field(default_factory=dict)
    anchored: bool = False
    anchor_url: str = ""
    #: FR-351 (v2.6.0/D62) — the cover best-of-N receipt that becomes `meta.yaml.cover_pick`:
    #: `{"candidates": [<asset-relative paths under covers/>, …], "chosen": <1-based candidate id>,
    #: "reason": <the pick's short prose>, "degraded": <bool>}`. `None` on every deck that never
    #: fanned out — `run.cover_candidates: 1`, an unchained deck, a run with no metered call to
    #: judge with — and on a fan-out where not one candidate landed, because there is then no
    #: choice to report. A PLAIN DICT for the same reason `AssetRecord.cover_pick` is one.
    cover_pick: dict[str, Any] | None = None
    outcomes: list[RenderOutcome] = field(default_factory=list)  # EVERY submission, failures too
    paths: dict[int, Path] = field(default_factory=dict)
    #: FR-95/FR-323 (v2.2.0): slide -> the Kie URL of its delivered render, kept for as long as the
    #: deck is being built. A re-render references the anchor AND its nearest delivered neighbour,
    #: and a neighbour is only referenceable while its provider URL is still held — discarding
    #: every non-anchor URL (as this module did until now) meant a re-rendered slide 5 could only
    #: look at the cover, and drifted from the four pages it sits between.
    urls: dict[int, str] = field(default_factory=dict)
    delivered: set[int] = field(default_factory=set)
    #: D49: slides the gauntlet's fix loop re-rendered at least once. Bookkeeping only — the round
    #: ceiling is the gauntlet's, so nothing here gates anything; it is what makes `retried_passed`
    #: an honest claim in `vision_check_result` (a deck that passed WITHOUT a re-render passed
    #: outright) and what the meta's rounds rows are cross-read against.
    rerendered: set[int] = field(default_factory=set)
    #: FR-317's SEPARATE one-shot ledger: the JOBS that have already been resubmitted once. A key
    #: is a slide number, or `(1, candidate_id)` for a cover candidate — each candidate is its own
    #: FR-317 ledger (FR-351), because three covers submitted concurrently are three jobs and a
    #: single shared key would hand the one retry to whichever of them happened to time out first,
    #: which is a scheduling accident rather than a policy. Kept apart from the gauntlet's
    #: re-renders on purpose — a gauntlet re-render is a FRESH submission with its own ledger rows
    #: and is never itself resubmitted (spec §7), while a slide whose job timed out is entitled to
    #: exactly one identical retry whatever the gate later says about it.
    resubmitted: set[Hashable] = field(default_factory=set)
    #: D49: this deck's whole gauntlet — the verdict, the rounds, the money. `None` while the gate
    #: has not run (disabled, no metered call, nothing delivered, an unsalvageable deck).
    report: gauntlet.GauntletReport | None = None
    #: What the fix loop has BILLED on THIS deck, in dollars, measured against
    #: `run.gauntlet.deck_budget_usd` inside the `RerenderFn` closure. The run cap is the budget's
    #: own business (`_submit` reserves against it); this is the per-deck ceiling on top.
    gauntlet_spend: float = 0.0
    #: F4: dollars this deck has CLAIMED for fix re-renders that are still in flight. The gauntlet
    #: re-renders every failing frame of a round CONCURRENTLY (`gauntlet._rerender_all` gathers
    #: them), so a cap read against `gauntlet_spend` alone is read by all of them before any of
    #: them has accrued: the 2026-08-14 run shipped eleven $0.03 re-renders against a $0.30 cap
    #: because eight of the eleven checks each saw $0.00. Held from before the submit until after
    #: the provider's own figure lands, exactly as `Budget.reserve`/`reconcile` hold the run cap.
    gauntlet_reserved: float = 0.0
    #: The lock the two above are read and written under — one per deck, because a deck's cap is a
    #: deck's own business and two carousels never share one. It exists for the ORDER of the
    #: read-modify-write, not for threads: this loop is a single event loop, and the race is the
    #: `await` between "does it fit" and "it is now claimed".
    gauntlet_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    #: F1-C: this run's fix-suffix reservation (`gauntlet.fix_reserve`), memoised on first use.
    #: `-1` means "not measured yet"; the sheet is read once per deck rather than once per slide.
    fix_reserve_chars: int = -1
    reasons: list[str] = field(default_factory=list)
    abandoned: bool = False
    #: D51's viability verdict: the reason ONE slide was permanently lost to a render defect, or
    #: `""` while the deck is still salvageable. Set once, never cleared except by FR-95's single
    #: re-anchor (a first anchor failure is not final until its replacement has also died), and
    #: read before every further submission for this deck.
    doomed: str = ""
    #: D51's other half: a submission the RUNWAY refused. Kept apart from `doomed` because it is
    #: not a defect — nothing was ordered, nothing was billed, and the deck ships what it has
    #: (10 §10's partial-deck row). It only suppresses FR-95's re-anchor, which would ask the same
    #: expired clock the same question.
    starved: bool = False
    #: FR-241/FR-270 (v2.1.4): which gpt-image-2 routes this deck's submissions actually took —
    #: `edit_route` for anything that carried references (the anchor, a brief photo, a mark patch),
    #: `text_route` for anything that carried none. Recorded rather than inferred, because the
    #: answer varies slide by slide inside one deck and `model_ids` may not claim a route this deck
    #: never used. Route NAMES stay in `render/profiles.py`; these are the configured ids.
    edit_route: bool = False
    text_route: bool = False

    def __post_init__(self) -> None:
        # FR-304/§0.4′: the deck's length was decided at ASSIGN from the bound source post's panel
        # count and is what the Confirm gate priced, so it is READ here, never re-derived. Copy no
        # longer shortens a deck: a source panel with no words is a wordless slide, not an absent
        # one, because slide i must stay aligned with source panel i (FR-302's position-preserving
        # grammar) and a deck that silently lost its middle would misalign every slide after it.
        copyset = self.copy
        written = list(copyset.slide_texts) if copyset else []
        # No headline fallback (D46): an unwritten slot renders wordless through the existing
        # no-text path. Repeating slide 1's line into it made a stutter the verbatim contract had
        # no opinion about, and it was the single most visible defect in the run that produced D46.
        self.texts = [written[i] if i < len(written) else "" for i in range(self._length())]
        # The look is ASSIGNED now, not re-derived per trend (FR-290/291): one registry entry for
        # the whole deck, so `style_dna` is a pure function of that entry and every slide of this
        # deck carries the same bytes (FR-189/M9) without anyone caching anything.
        self.style = style_of(self.entry, self.env)
        self.dna = style_dna(self.style)  # FR-189: ONCE per deck
        self.branding = branding_block(self.entry, self.env, self.style)
        self.wordmark = wordmark(self.entry, self.env)
        # D-D: ONCE per deck, like the DNA — the convention is a fact about the source we are
        # mirroring, so re-detecting it per slide could only produce a deck that counts itself in
        # two hands. The numbers are re-based per slide by `_counter()`.
        self.counter = self._counter_spec()

    # ------------------------------------------------------------------------------- ordering

    async def build(self) -> None:
        """Anchor, re-anchor, deck — or the unchained fallback when neither anchor lands."""
        self._mark_truncation()
        self.attached = await attach(self.entry, self.env, self.folder)
        await self._crop_patches()  # FR-315: once per deck, before the first slide is priced
        self.anchored = bool(self.env.config.run.carousel_anchor)
        if self.anchored:
            losses = len(self.reasons)
            await self._anchor()
            if not self.anchor_url:
                await self._reanchor(losses)
            if self.anchor_url:
                await self._anchor_gate()  # D49: BEFORE slides 2–N exist to copy it
                if not self._blocked:  # a leaking cover buys no body pages (FR-325)
                    await self._burst(range(2, len(self.texts) + 1))
                    await self._gauntlet()
                return
            self.anchored = False
            # The unchained burst renders slide 1 AGAIN, from scratch, alongside every other slide
            # — so the cover is not lost yet and the deck is not unsalvageable yet. D51's gate asks
            # "has this slide run out of paths"; FR-95 says the anchor has one more. Both the doom
            # and the anchor phase's loss lines are therefore cleared: what the burst does or does
            # not deliver is recorded by the burst.
            self.doomed = ""
            del self.reasons[losses:]
            self.env.log.warn(
                "carousel_anchor_fallback_unchained",
                f"{self.entry.asset_id}: slide 1 never landed and neither did its one replacement; "
                "the deck falls back to UNCHAINED generation — every slide rendered independently "
                "from the style DNA and its own text, with no anchor to copy (FR-95)",
                asset_id=self.entry.asset_id, slides=len(self.texts))
        # The FR-95 fallback and the `carousel_anchor: false` A/B control are the same shape, and
        # both are PRE-COMMITTED wave-2 work — never discretionary (FR-106b, plan §2 T4.3).
        await self._burst(range(1, len(self.texts) + 1))
        await self._gauntlet()

    async def _reanchor(self, losses: int) -> None:
        """FR-95 (v2.2.0): ONE replacement anchor before the deck gives up on being chained.

        The old shape was all-or-nothing in the wrong direction: a single failed cover — a timeout,
        a provider hiccup, one moderation refusal — condemned every remaining slide to independent,
        reference-free generation, and an unchained deck is the defect the anchor exists to prevent
        (the 08-14 audit's decks 3 and 9 are both this). One more cover render is the cheapest
        possible repair: it costs ONE image against a deck of five to nine, and when it lands the
        deck is chained exactly as designed. The Confirm gate already prices it — `budget.py`'s
        anchor contingency is two units for precisely this shape (FR-107).

        Pre-committed spend (FR-106b), like every other FR-95 fallback: the cap may not decline the
        one render that decides whether the operator gets a deck or nine strangers.

        Refused in three states, each because the answer is already known: a halted run and an
        exhausted credit balance stop ordering outright (FR-201/108/167), and a RUNWAY-refused
        first attempt (D51) would ask the same expired clock the same question. A first attempt
        lost to a real render defect is NOT one of them — that is the case this exists for — so
        `doomed` is cleared for the retry: slide 1 is not permanently lost until its one
        replacement has died too.
        """
        env = self.env
        if env.halted or env.credits_exhausted or self.starved:
            return
        cause = self.doomed or "the first attempt never delivered"
        self.doomed = ""  # not final until the replacement dies (see the docstring)
        env.log.warn(
            "carousel_anchor_retry",
            f"{self.entry.asset_id}: the anchor never landed ({cause}); one replacement anchor is "
            "ordered before the deck is unchained (FR-95, attempt 2 of 2)",
            asset_id=self.entry.asset_id, slide=1)
        await self._slide(1, anchor=False, kind="precommitted", priority=RenderPriority.WAVE1)
        if self.anchor_url:
            # The first attempt's failure is evidence, not a loss: `self.reasons` is the ledger of
            # slides that are MISSING, and slide 1 is on disk. Both attempts stay in the log.
            del self.reasons[losses:]

    def _mark_truncation(self) -> None:
        """FR-304/FR-257: say so when the source deck was longer than this platform's ceiling.

        The cut itself happened at ASSIGN (`plan.deck_length` kept the first N panels, indices
        preserved); what is owed here is the honest label on the artifact — the operator comparing
        our deck with the source in the gallery must be able to see that panels 6..N were never
        ordered, rather than reading it as slides that failed to render.
        """
        post = self.source_post
        panels = source_panel_count(post) if post is not None else 0
        if post is None or panels <= len(self.texts):
            return
        self.folder.mark(PANELS_TRUNCATED)
        self.env.log.warn(
            "carousel_panels_truncated",
            f"{self.entry.asset_id}: source post {post.post_id} has {panels} panels and this "
            f"platform's ceiling is {len(self.texts)} — source panels "
            f"{len(self.texts) + 1}–{panels} are not rendered (FR-304/FR-257)",
            asset_id=self.entry.asset_id, source_post_id=post.post_id, source_panels=panels,
            slides=len(self.texts))

    async def _crop_patches(self) -> None:
        """FR-315: cut this deck's detected marks out of their source slides and upload them once.

        ONE crop pass and ONE upload per distinct mark for the whole deck, because a mark boxed on
        eight panels is the same logo eight times (`logo_crops.crop_marks` de-duplicates by name,
        `refs.upload_local` de-duplicates by path through the run memo). The result is a small
        `{mark -> URL}` table every slide reads; nothing here is per slide.

        Every branch is fail-open (FR-315d), and each costs pixels only: no slide intelligence, no
        `mark_boxes`, no stored source folder, a crop Pillow refused, an upload Kie refused. The
        mark then renders from its name plus the template's written description, which is the
        documented fallback — a missing patch may never cost a slide, and it never blocks one.

        NOTHING UNSANCTIONED IS CUT (v2.2.0). The allowlist handed to `crop_marks` is the union of
        every slide's own D-A sanction list, collapsed — so a competitor's logo, the creator's own
        mark, platform chrome and any mark boxed only on a SOURCE PANEL BEYOND OUR DECK's length
        are never cropped, never written to disk and never uploaded. The sanction gate used to sit
        at attachment only (`_patch_refs`), which meant a nine-panel source with a competitor logo
        on panel 8 uploaded that logo to Kie for a five-slide deck that could never legitimately
        show it: an upload the D48 carve-out does not cover. The gate now sits at the knife.

        The crop is SYNCHRONOUS (file read + decode + PNG write) and runs on a worker thread: it is
        real work, and the event loop here is also carrying every other creative in the run.
        """
        intel = self._intel()
        boxes = list(getattr(intel, "mark_boxes", ()) or ()) if intel is not None else []
        folder = str(getattr(intel, "folder", "") or "")
        run_dir = getattr(self.env, "run_dir", "")
        allow = self._allowed_marks()
        if not boxes or not folder or not run_dir or not allow:
            return
        try:
            cropped = await asyncio.to_thread(crop_marks, Path(run_dir) / folder, boxes,
                                              allow=allow)
        except Exception as exc:  # noqa: BLE001 — pixels are an upgrade; the deck ships without
            self.env.log.warn(
                "logo_patch_unavailable",
                f"{self.entry.asset_id}: the source slides could not be cropped for logo patches "
                f"({type(exc).__name__}: {exc}); every sanctioned mark renders from its name and "
                "description instead (FR-315d)", asset_id=self.entry.asset_id)
            return
        for name, path in cropped.items():
            url = await upload_local(path, self.env,
                                     label=f"{self.entry.asset_id} mark patch {name}")
            if url:
                self.patches[collapse(mark_name(name))] = url
        self.env.log.event(
            "mark_patches_ready",
            f"{self.entry.asset_id}: {len(self.patches)} of {len(cropped)} cropped mark patch(es) "
            f"uploaded from {len(boxes)} detected box(es)", asset_id=self.entry.asset_id,
            boxes=len(boxes), cropped=len(cropped), uploaded=len(self.patches),
            marks=sorted(cropped))

    def _allowed_marks(self) -> frozenset[str]:
        """FR-315's crop allowlist: every mark THIS deck may legitimately draw, collapsed.

        The union of `_sanctioned_marks(n)` over the slides we actually render — 1..len(texts), not
        the source's panel count — spelled the way the patch table is keyed (`collapse(mark_name)`),
        which is the same spelling `_patch_refs` joins on. One vocabulary end to end: a name that
        cannot pass the sanction gate cannot reach the knife, and a name that passed it here will
        match its patch at attachment.
        """
        return frozenset(collapse(mark_name(name))
                         for number in range(1, len(self.texts) + 1)
                         for name in self._sanctioned_marks(number))

    async def _burst(self, numbers: range) -> None:
        """Every remaining slide at once — inside a wave nothing waits for a sibling (FR-25).

        Unless the deck is already unsalvageable (D51). One slide permanently lost to a render
        defect means this deck can never be the deck that was approved: a carousel is read as a
        sequence, our slide *i* IS source panel *i* (FR-304), and a hole in the middle is not a
        shorter deck but a broken one. Everything still unordered is therefore skipped BEFORE the
        money door rather than rendered into a deck that will not ship — the whole point of the
        gate is that the remaining N−1 renders are never bought.

        What is NOT done here, ever: cancelling. Jobs already submitted are already billed
        (FR-29/FR-203), so they run to their own terminal line and are recorded like any other.
        """
        if self.doomed:
            self._short_circuit(numbers)
            return
        await asyncio.gather(*(
            self._slide(number, anchor=self.anchored, kind="precommitted",
                        priority=RenderPriority.WAVE2) for number in numbers))

    def _short_circuit(self, numbers: range) -> None:
        """D51: name every slide this deck will not order, in ONE line plus one reason each."""
        skipped = [number for number in numbers if number not in self.delivered]
        if not skipped:
            return
        # Straight into the loss ledger rather than through `_note`: these are not N independent
        # setbacks, they are one decision with N consequences, and N warn lines would bury the
        # single line that explains them.
        # The per-slide line names the DECISION, not the sibling's failure: repeating the doom
        # cause N times would put slide 3's provider error in slide 6's explanation, and the deck's
        # own line below carries the cause once, in full.
        self.reasons.extend(f"slide {number}: {_UNSALVAGEABLE}" for number in skipped)
        self.env.log.warn(
            "deck_viability_short_circuit",
            f"{self.entry.asset_id}: {self.doomed}; a slide permanently lost to a render defect "
            f"cannot be re-ordered, so slides {skipped} are not submitted at all and the deck is "
            "kept off the run's published work (D51). Jobs already in flight are never cancelled — "
            "they are billed and are recorded as they land (FR-29/FR-203)",
            asset_id=self.entry.asset_id, cause=self.doomed, not_ordered=skipped,
            delivered=sorted(self.delivered))

    # ------------------------------------------------------- FR-351: the cover pick (v2.6.0/D62)

    async def _anchor(self) -> None:
        """Buy the deck's cover: ONE slide-1 render, or `cover_candidates` of them and choose.

        FR-351 (D62). `run.cover_candidates: 1` is the pre-D62 path byte for byte — a single
        `_slide(1, …)`, no fan-out, no pick call, `self.cover_pick` left `None` — because a cover
        nobody chose between has no choice to write down.

        Above 1 the SAME request is submitted that many times CONCURRENTLY. The prompt is a pure
        function of this deck's own inputs, so every candidate is the identical order and the only
        thing that varies is the provider's sampling; perturbing the prompt per candidate would
        make them incomparable, because the judge would then be choosing between two briefs rather
        than between two readings of one. Concurrency matters as much as sameness: these are
        wave-1 jobs and the whole deck waits behind them, so three covers in sequence would put
        two render round-trips on the run's critical path for nothing.

        Each candidate rides `_call`, so FR-97's reference-free moderation retry and FR-317's one
        resubmit apply PER CANDIDATE, and every submission joins `self.outcomes` for the billing
        tally exactly as a lone anchor's does (FR-29/FR-203). Only ONE of them becomes `slide_01`
        and `anchor_url`; the rest are kept as `covers/` files so the operator can see what was
        turned down, and none of them is ever a missing slide.

        The whole fan-out is invisible to everything downstream: `_reanchor` still orders ONE
        replacement (FR-95 is about a cover that never came, not about a cover that lost), and
        `_anchor_gate` still judges whatever `slide_01` turned out to be.
        """
        losses = len(self.reasons)
        wanted = self._cover_wanted()
        if wanted <= 1:
            await self._slide(1, anchor=False, kind="projected", priority=RenderPriority.WAVE1)
            return
        outcomes = await asyncio.gather(*(
            self._render(1, anchor=False, kind="projected", priority=RenderPriority.WAVE1,
                         ledger=(1, candidate))
            for candidate in range(1, wanted + 1)))
        await self._choose_cover(list(outcomes), losses)

    def _cover_wanted(self) -> int:
        """How many slide-1 renders to order — and the one case where the answer is trimmed to 1.

        `run.cover_candidates` is bounded 1–3 at config load (`config._BOUNDS`), so the only
        judgement left here is whether there is anything to judge WITH. A run whose `Env` carries
        no metered call — the gauntlet off and the pick seam unwired, a preview, a unit test —
        would buy two or three covers, be unable to ask which of them is best, and commit the
        first: the deck a `cover_candidates: 1` run makes, for three times the render spend. Renders
        nobody can judge are waste, so the extras are never ordered and the operator is told once,
        on this deck, rather than left to find the money in the ledger afterwards.
        """
        wanted = max(1, int(getattr(self.env.config.run, "cover_candidates", 1) or 1))
        if wanted > 1 and self.env.llm_call is None:
            self.env.log.warn(
                "cover_candidates_unjudged",
                f"{self.entry.asset_id}: {wanted} covers were ordered but no metered call is "
                "wired to choose between them; one cover is rendered (FR-351)",
                asset_id=self.entry.asset_id, cover_candidates=wanted)
            return 1
        return wanted

    async def _choose_cover(self, outcomes: list[RenderOutcome | None], losses: int) -> None:
        """Commit ONE fanned-out cover as slide 1 and file the receipt for every candidate.

        Three shapes, and the difference between them is which question is still open:

        * **nothing landed** — the deck has no cover, exactly as a lone failed anchor leaves it.
          ONE of the outcomes goes through `_store` so the D51 defect bookkeeping, the `doomed`
          latch and FR-95's `_reanchor` all run precisely as they did before this method existed.
          One loss line, not `wanted` of them: three candidates dying of one provider fault is one
          setback with three receipts, and three identical lines in `missing_slide_numbers`'
          explanation would read as three separate slides.
        * **one landed** — there is nothing to choose. `cover_pick.pick` says so itself on a
          single candidate (a non-degraded verdict with a plain reason), so this path is not
          special-cased here: one call site, one vocabulary, no second opinion about what "no
          choice" means.
        * **two or more landed** — the metered pick runs, and whatever it answers the deck gets a
          cover. A degraded verdict commits candidate 1 and wears `cover_pick_degraded`; it never
          costs the deck a slide, because the pick is a judgement about renders that already
          exist (§0.14c's fail-open shape, borrowed whole from the style matcher).

        Candidates that FAILED are logged as `cover_candidate_lost` and are deliberately kept OUT
        of `self.reasons` and out of D51's doom: the slide they were competing for arrived. D51 is
        about a slide that can never come, and this one came.
        """
        env = self.env
        landed = [(number, outcome) for number, outcome in enumerate(outcomes, start=1)
                  if outcome is not None and outcome.kind is RenderOutcomeKind.SUCCESS
                  and outcome.result_urls]
        env.log.event(
            "cover_candidates",
            f"{self.entry.asset_id}: {len(outcomes)} cover candidate(s) submitted for slide 1, "
            f"{len(landed)} landed (FR-351)",
            asset_id=self.entry.asset_id, submitted=len(outcomes), landed=len(landed),
            candidates=[number for number, _ in landed])
        # The fan-out's own notes are dropped and re-stated below at the right cardinality: every
        # candidate that was declined, refused or 402'd has already appended a line through
        # `_submit`, and `wanted` copies of one sentence is not a ledger of missing slides.
        notes = self.reasons[losses:]
        del self.reasons[losses:]
        if not landed:
            first = next((outcome for outcome in outcomes if outcome is not None), None)
            if first is not None:
                await self._store(1, first, lost=True)  # THE loss line, the defect, the doom
            elif notes:
                self.reasons.append(notes[0])  # nothing was ever ordered: one refusal, stated once
            return
        self._note_cover_losers(outcomes, landed)
        fetched = await self._cover_bytes(landed)
        stored = self._store_candidates(fetched)
        verdict = await self._pick_cover(fetched, landed)
        winner = next((outcome for number, outcome, _ in fetched if number == verdict.chosen),
                      landed[0][1])
        await self._store(1, winner, lost=True)
        self.cover_pick = {"candidates": [stored[number] for number in sorted(stored)],
                           "chosen": verdict.chosen, "reason": verdict.reason,
                           "degraded": verdict.degraded}
        if verdict.degraded:
            self.folder.mark(DegradationTag.COVER_PICK_DEGRADED)
            env.log.warn(
                "cover_pick_degraded",
                f"{self.entry.asset_id}: the cover pick could not be made ({verdict.reason}); "
                f"candidate {verdict.chosen} anchors the deck by default and every candidate is "
                f"kept under {COVERS_DIR}/ (FR-351)",
                asset_id=self.entry.asset_id, chosen=verdict.chosen, landed=len(landed),
                reason=verdict.reason)
        else:
            env.log.event(
                "cover_pick",
                f"{self.entry.asset_id}: cover {verdict.chosen} of {len(landed)} anchors the deck "
                f"— {verdict.reason}",
                asset_id=self.entry.asset_id, chosen=verdict.chosen, landed=len(landed),
                reason=verdict.reason)

    def _note_cover_losers(self, outcomes: list[RenderOutcome | None],
                           landed: list[tuple[int, RenderOutcome]]) -> None:
        """Say which candidates never came back — as WARNINGS, never as missing slides (FR-351).

        A candidate that failed cost money and produced nothing, which is worth a line; it did not
        cost the deck anything, which is why the line is not in `self.reasons`, does not carry
        `defect=True` and cannot reach `doomed`. A landed candidate that simply was not chosen is
        not mentioned here at all — losing a comparison is not a failure, and its bytes are on
        disk under `covers/` for the operator to look at.
        """
        won = {number for number, _ in landed}
        for number, outcome in enumerate(outcomes, start=1):
            if number in won:
                continue
            cause = ("nothing was ordered — the cap, the runway or the credit balance refused it"
                     if outcome is None else
                     (outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value))
            self.env.log.warn(
                "cover_candidate_lost",
                f"{self.entry.asset_id}: cover candidate {number} of {len(outcomes)} did not land "
                f"({cause}); {len(landed)} did, so slide 1 is not missing and the deck is not "
                "unsalvageable (FR-351)",
                asset_id=self.entry.asset_id, candidate=number, cause=cause, landed=len(landed),
                detail=None if outcome is None else outcome.fail_message)

    async def _cover_bytes(self, landed: list[tuple[int, RenderOutcome]]
                           ) -> list[tuple[int, RenderOutcome, bytes]]:
        """Fetch each landed candidate's NATIVE bytes, still tied to the id it was submitted under.

        `load_images` returns `(blobs, positions)` where a position is the 1-based index in what it
        was HANDED, so the candidate id is recovered through `landed` rather than by counting the
        blobs: a cover whose download failed is dropped by that loader, and a list read positionally
        after a drop would silently re-label every candidate behind it — the judge would then be
        told candidate 3 is candidate 2, and the deck would anchor to the wrong render.
        """
        blobs, positions = await load_images(
            [outcome.result_urls[0] for _, outcome in landed], self.env.log)
        return [(landed[position - 1][0], landed[position - 1][1], blob)
                for position, blob in zip(positions, blobs)]

    def _store_candidates(self, fetched: list[tuple[int, RenderOutcome, bytes]]) -> dict[int, str]:
        """Keep EVERY landed cover on disk under `covers/`, winner included. `{id: path}`.

        The winner is written twice on purpose — here as `covers/cover_candidate_2.jpg` and again
        as `slide_01.jpg` by `_store` — because a strip missing its chosen tile is a strip the
        operator has to reconstruct against the deck beside it. Uniformity is the point of the
        strip: three thumbnails, one of them outlined, and the comparison reads at a glance.

        Fail-open in both directions (FR-351d's shape, and FR-315's before it): a candidate whose
        bytes will not write is left out of `candidates` and warned about, and nothing here can
        cost the deck a slide — the cover is committed from its provider URL by `_store`, not from
        these files. `PackagingError` covers the packager's own two reasons (`disk_full`,
        `write_failed`); `OSError` covers anything that escapes it.

        A full disk is the one failure that outlives this creative (10 §10), so it is both read
        BEFORE the loop — nothing is written when the run has already found the disk full — and
        LATCHED when it is found here. The alternative is a deck writing three rejected covers on
        a volume that has no room for the slide it is about to keep.
        """
        stored: dict[int, str] = {}
        if self.env.disk_full:
            return stored
        for number, outcome, blob in fetched:
            # `render_name` is the packager's OWN public answer to "what extension do bytes from
            # this URL get", fallback included. Asking it keeps the single extension table in the
            # module that owns it instead of re-deriving a URL suffix — and re-deriving is how a
            # `.png` result would have landed in a file called `.jpg`.
            suffix = Path(self.folder.render_name(outcome.result_urls[0])).suffix or ".jpg"
            name = f"{COVERS_DIR}/{COVER_CANDIDATE_STEM}_{number}{suffix}"
            try:
                self.folder.store_bytes(blob, name)
            except (PackagingError, OSError) as exc:
                if getattr(exc, "reason", "") == "disk_full":
                    self.env.disk_full = True  # run-wide from here on (10 §10)
                self.env.log.warn(
                    "cover_candidate_unsaved",
                    f"{self.entry.asset_id}: cover candidate {number} could not be written to "
                    f"{name} ({type(exc).__name__}: {exc}); it is left out of the gallery strip "
                    "and the deck is unaffected (FR-351)",
                    asset_id=self.entry.asset_id, candidate=number, name=name)
                continue
            stored[number] = name
        return stored

    async def _pick_cover(self, fetched: list[tuple[int, RenderOutcome, bytes]],
                          landed: list[tuple[int, RenderOutcome]]) -> cover_pick.Pick:
        """Ask which cover anchors the deck. Always answers; never raises; never blocks (FR-351).

        A judge needs pixels, so `fetched` — not `landed` — is what can be asked about. When every
        download failed there is nothing to show anyone: the first landed cover anchors the deck,
        and that counts as a DEGRADE only when two or more landed, because only then was there a
        real question that went unasked.

        `env.halted` and `credits_exhausted` are re-read HERE, between the fan-out and the commit,
        for the same reason every submission re-reads them: the candidates may have spent the whole
        render timeout inside the window where Ctrl+C or the deadline landed. A stopped run does
        not buy one more metered call to rank pictures it is about to stop shipping — it commits
        the first landed candidate, says why, and wears NO degradation tag, because nothing was
        degraded: the operator stopped the run.

        The answer's `chosen` is policed against the ids actually handed over. `cover_pick`
        guarantees a valid id and a caller that trusted the guarantee would still be one provider
        surprise away from `StopIteration` on the commit — so an id this deck does not recognise
        falls back to the first landed candidate and is reported as a degrade, which is exactly
        what an unusable answer is.
        """
        env = self.env
        first = fetched[0][0] if fetched else landed[0][0]
        if not fetched:
            degraded = len(landed) > 1
            cause = "no candidate's bytes could be fetched, so none could be shown to a judge"
            env.log.warn(
                "cover_pick_unfetched",
                f"{self.entry.asset_id}: {cause}; candidate {first} anchors the deck (FR-351)",
                asset_id=self.entry.asset_id, chosen=first, landed=len(landed))
            return cover_pick.Pick(
                chosen=first, degraded=degraded,
                reason=f"{cover_pick.DEGRADED_MARKER}: {cause}" if degraded else cause)
        if env.halted or env.credits_exhausted:
            env.log.warn(
                "cover_pick_skipped",
                f"{self.entry.asset_id}: the run stopped ordering work, so the cover pick is not "
                f"made; candidate {first} anchors the deck and every landed candidate is kept "
                f"under {COVERS_DIR}/ (FR-351/FR-201)",
                asset_id=self.entry.asset_id, chosen=first, candidates=len(fetched))
            return cover_pick.Pick(chosen=first,
                                   reason="the run stopped before the covers could be judged")
        verdict = await cover_pick.pick(
            [cover_pick.CoverCandidate(index=number, image=blob) for number, _, blob in fetched],
            cover_pick.CoverBrief(
                asset_id=self.entry.asset_id,
                style_key=self.style.key if self.style is not None else "",
                # The EXACT bytes every slide of this deck was rendered under (FR-189/M9): the
                # judge holds the candidates against the contract they were ordered from, not
                # against a paraphrase of it.
                style_dna=self.dna,
                expected_text=tuple(
                    text for text in (self.texts[0] if self.texts else "", self.wordmark,
                                      self._counter(1)) if text.strip()),
                counter=self._counter(1)),
            env.config, env.llm_call)
        if verdict.chosen in {number for number, _, _ in fetched}:
            return verdict
        env.log.warn(
            "cover_pick_out_of_range",
            f"{self.entry.asset_id}: the cover pick named candidate {verdict.chosen}, which this "
            f"deck never submitted; candidate {first} anchors it instead (FR-351)",
            asset_id=self.entry.asset_id, answered=verdict.chosen, chosen=first)
        return replace(verdict, chosen=first, degraded=True,
                       reason=f"{cover_pick.DEGRADED_MARKER}: the pick named a candidate "
                              f"({verdict.chosen}) this deck never submitted")

    async def _slide(
        self, number: int, *, anchor: bool, kind: ReserveKind, priority: RenderPriority,
        fix: str = "",
    ) -> bool:
        """Render one slide and put its bytes on disk. True when that slide was delivered.

        Submit then commit, and the two halves are separate methods because the COVER can be
        bought more than once (FR-351/D62): `_anchor` fans `_render` out `cover_candidates` times
        and commits exactly one of the outcomes through `_store`. Every other slide is this
        one-in-one-out pairing, unchanged — a submission whose bytes go straight to disk.

        `fix` is the gauntlet's CANNED remedy suffix (FR-323) when this is a fix-loop re-render, and
        `""` on a first pass. It changes the request and never the words: the TEXT block is
        byte-identical on both, because the strings are LOCKED CONTRACT STRINGS — a verbatim quote
        of the source panel, or its D54-compressed text — and shortening one to make it fit is the
        defect the gate exists to catch. Compress mode changes WHO shortened the panel and WHEN
        (the copy model, before any render was submitted, to the style's declared budget); it does
        not license this stage to shorten anything.
        """
        outcome = await self._render(number, anchor=anchor, kind=kind, priority=priority, fix=fix)
        if outcome is None:
            return False
        # A gauntlet RE-RENDER can fail without losing anything: the slide it was improving is
        # already on disk and already shipping. Its failures are therefore logged but kept out of
        # `self.reasons`, which is the deck's ledger of slides that are MISSING — a "slide 3:
        # declined by the spend cap" line beside `missing_slide_numbers: [5]` told the operator
        # slide 3 was lost when slide 3 was delivered (FR-73).
        return await self._store(number, outcome, lost=not fix)

    async def _render(
        self, number: int, *, anchor: bool, kind: ReserveKind, priority: RenderPriority,
        fix: str = "", ledger: Hashable | None = None,
    ) -> RenderOutcome | None:
        """Order one slide and hand back the finished job — the SUBMIT half of `_slide`.

        Nothing here touches disk, `self.delivered`, `self.urls` or `self.anchor_url`: this is the
        stage that decides whether a render is bought and what it is asked for, and `_store` is
        the stage that decides what becomes of what came back. Splitting them is what lets FR-351
        buy two or three covers concurrently and commit one of them, without a second copy of the
        halt/credits/doom guards, the reference assembly, the prompt cap or the route bookkeeping.

        `None` means nothing came back to commit, and it is the same `None` `_slide` has always
        turned into `False`: a halted run, an exhausted balance, an unsalvageable deck, a prompt
        that would not assemble, or a submission the cap, the runway or the 402 refused. Every one
        of those has already been NOTED by the time it returns, so the caller adds no explanation.

        `ledger` names FR-317's one-shot bucket for THIS submission and defaults to the slide
        number, which is every caller but one: a slide gets one automatic resubmit, and the FR-95
        replacement anchor deliberately shares slide 1's bucket exactly as it always has. FR-351's
        fan-out is the exception and passes `(1, candidate_id)`, because its candidates are
        concurrent, independent jobs — see `_resubmit`.
        """
        env = self.env
        # A gauntlet RE-RENDER can fail without losing anything: the slide it was improving is
        # already on disk and already shipping. Its failures are therefore logged but kept out of
        # `self.reasons`, which is the deck's ledger of slides that are MISSING — a "slide 3:
        # declined by the spend cap" line beside `missing_slide_numbers: [5]` told the operator
        # slide 3 was lost when slide 3 was delivered (FR-73).
        lost = not fix
        if env.halted:  # re-read before EVERY submission (FR-201/108)
            self.abandoned = self.abandoned or not self.outcomes
            self._note(f"slide {number}: interrupted before submission", lost=lost)
            return None
        if env.credits_exhausted:
            self._note(f"slide {number}: {_CREDITS}", lost=lost)
            return None
        if self.doomed:  # D51: nothing more is ordered for a deck that can no longer be whole
            self._note(f"slide {number}: {_UNSALVAGEABLE}", lost=lost)
            return None
        refs = await self._refs(number, anchor, rerender=bool(fix))
        prompt = self._prompt(number, anchor=anchor, refs=refs, fix=fix)
        if prompt is None:
            # A defect of OUR making, and a deterministic one: the same context will not fill the
            # same template on a second ask, so this slide is permanently lost (D51).
            self._note(f"slide {number}: prompt_assembly_failed — unresolved placeholder "
                       "(FR-260)", error=True, lost=lost, defect=True)
            return None
        urls = [ref.url for ref in refs]
        # FR-241 decides the route by exactly this test inside `render/profiles.py`, so recording
        # it here is an observation of the same fact rather than a second opinion about it.
        self.edit_route = self.edit_route or bool(urls)
        self.text_route = self.text_route or not urls
        return await self._call(number, prompt, urls, kind=kind, priority=priority, lost=lost,
                                ledger=ledger)

    async def _store(self, number: int, outcome: RenderOutcome, *, lost: bool) -> bool:
        """One finished job -> one slide file on disk. True when that slide is deliverable.

        Shared by the first pass, by FR-351's chosen cover and by the gauntlet's fix loop, which is
        the whole reason it is a method: each has to hold the result URL for a neighbour reference,
        each has to re-point the anchor when slide 1 moves, and each has to answer a full disk the
        same way. Two copies of that would be two decks that disagree about which slide 1 the body
        pages copy.
        """
        env = self.env
        url = outcome.result_urls[0] if outcome.result_urls else ""
        if outcome.kind is not RenderOutcomeKind.SUCCESS or not url:
            # FR-242: a `success` with nothing behind it is a failure that lies.
            cause = outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value
            # D51: this is a terminal render failure AFTER FR-317's one resubmit, so the slide is
            # permanently lost — unless the run itself stopped underneath it (a halt, an exhausted
            # balance), which is an abandonment and keeps 10 §10's partial-deck behaviour. A runway
            # refusal never reaches here at all: `_submit` returns `None` for it. A GAUNTLET fix
            # re-render is never a defect either (`lost=False`): the slide it was improving is
            # already on disk, so nothing was lost and the deck stays salvageable.
            defect = lost and not (env.halted or env.credits_exhausted
                                   or outcome.fail_cause is RenderFailCause.CREDITS_EXHAUSTED
                                   or outcome.fail_cause is RenderFailCause.NO_RUNWAY)
            return self._note(f"slide {number}: {cause} — "
                              f"{outcome.fail_message or 'no usable result'}", error=True,
                              lost=lost, defect=defect)
        self.urls[number] = url  # FR-323: referenceable by its neighbours while the deck is built
        if number == 1:
            self.anchor_url = url  # the deck anchors to the FINAL slide 1 (10 §5)
        if env.disk_full:  # 10 §10: further downloads STOP rather than thrash a full disk
            return self._note(f"slide {number}: disk_full — downloads stopped for this run",
                              lost=lost)
        try:  # the bytes stop being a borrowed 24 h URL and become the operator's file
            self.paths[number] = await self.folder.store_render(url, slide=number)
        except PackagingError as exc:  # one lost slide, never a lost deck
            if exc.reason == "disk_full":  # the one failure that outlives this creative
                env.disk_full = True
            # NOT a D51 defect, either shape. A full disk is 10 §10's run-wide condition, and a
            # failed download is our end of a job the PROVIDER completed — both describe the
            # workstation rather than the render, and both keep the partial deck that ships.
            return self._note(f"slide {number}: {exc.reason}", error=True, lost=lost)
        self.delivered.add(number)
        return True

    async def _call(
        self, number: int, prompt: str, urls: list[str], *, kind: ReserveKind,
        priority: RenderPriority, lost: bool = True, ledger: Hashable | None = None,
    ) -> RenderOutcome | None:
        """The one door to `submit`: tally every outcome, apply FR-97 and FR-317, swallow the 402.

        Two single retries live here and they answer different questions. FR-97's is about the
        REQUEST — a content-policy refusal is re-asked without its references, because that is
        what a moderation refusal is usually about. FR-317's is about the JOB — a timeout or an
        ordinary provider failure is the same request again, unchanged, because nothing about it
        was wrong (D48). They never stack on one attempt: a moderation refusal is excluded from
        FR-317 by name, and whichever attempt is standing when the retries are done is returned.

        `ledger` is passed straight through to `_resubmit` and names FR-317's one-shot bucket;
        `None` means "this slide's own number", which is what every caller outside FR-351's
        cover fan-out wants and what this method did before the parameter existed.
        """
        outcome = await self._submit(prompt, urls, kind=kind, priority=priority, lost=lost,
                                     label=f"carousel slide {number}/{len(self.texts)}"
                                           f"{self._panel_note(number)}"
                                           f" · {self.entry.asset_id}")
        if (outcome is not None and outcome.kind is not RenderOutcomeKind.SUCCESS
                and outcome.fail_cause is RenderFailCause.MODERATION and urls):
            self.env.log.warn("moderation_retry",
                              f"{self.entry.asset_id} slide {number}: content-policy refusal; one "
                              "reference-free retry (FR-97)", asset_id=self.entry.asset_id,
                              slide=number, detail=outcome.fail_message)
            retry = await self._submit(prompt, [], kind="discretionary", priority=priority,
                                       lost=lost, label=f"moderation retry · slide {number}")
            if retry is not None:
                self.folder.mark(DegradationTag.REFS_DROPPED_MODERATION)
                outcome, urls = retry, []
        return await self._resubmit(number, prompt, urls, outcome, priority=priority,
                                    lost=lost, ledger=ledger)

    async def _resubmit(
        self, number: int, prompt: str, urls: list[str], outcome: RenderOutcome | None, *,
        priority: RenderPriority, lost: bool, ledger: Hashable | None = None,
    ) -> RenderOutcome | None:
        """FR-317's ONE automatic resubmit of a timed-out or non-moderation-failed slide job.

        Returns the outcome the caller should treat as this attempt's result: the resubmission when
        one happened and produced anything at all, otherwise the failure it was given. A second
        failure is FINAL — the slide flows into the ordinary lost-slide path with the second job's
        own cause, and `self.resubmitted` guarantees there is never a third.

        **One ledger per JOB, not per slide number** (FR-351, v2.6.0/D62). `ledger` defaults to
        `number`, which is the pre-D62 bucket and keeps every existing caller byte-identical —
        including FR-95's replacement anchor, which shares slide 1's bucket exactly as it always
        has. The cover fan-out passes `(1, candidate_id)` instead, because its two or three
        candidates are submitted CONCURRENTLY and are separate jobs: sharing one key would have
        given the single retry to whichever candidate's timeout landed first and silently denied
        it to the others, and which one won would be a scheduling accident rather than a policy.
        The operator-facing strings are untouched — every line still says `slide 1`, because that
        is the slide being bought — and the candidate id rides the structured fields instead, for
        whoever is reading `events.jsonl`.

        Deliberately NOT applied to:
        * a moderation refusal — FR-97 owns that failure and answering it with the identical
          request would buy the identical refusal;
        * a declined submission (`None`) — nothing was ordered, so there is nothing to re-order;
        * a RUNWAY refusal (`NO_RUNWAY`, D51) — excluded BY NAME even though `_submit` already
          converts one to `None`, because this predicate is the guarantee and the conversion is an
          implementation detail: a refusal that cost nothing may never burn the one attempt FR-317
          grants a job that really failed, and a clock that had no room a moment ago has less now;
        * a halted or credit-exhausted run — `env.halted` is re-read HERE, immediately before the
          resubmission, because the first attempt may have spent the whole timeout inside the
          window where Ctrl+C landed (FR-201/108/167).

        The money is `discretionary` (FR-106c): a resubmit is real, optional spend the cap may
        decline, and the timed-out attempt it replaces already reconciled at $0 (`_billed_usd`),
        so a deck that resubmits is billed for the renders it got, not for the ones that never
        came back.
        """
        env = self.env
        key: Hashable = number if ledger is None else ledger
        if self.doomed:  # D51: a sibling slide is already permanently lost — buy nothing more
            return outcome
        if (outcome is None or outcome.kind is RenderOutcomeKind.SUCCESS
                or outcome.fail_cause is RenderFailCause.MODERATION
                or outcome.fail_cause is RenderFailCause.NO_RUNWAY
                or key in self.resubmitted):
            return outcome
        cause = outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value
        # WHICH of three concurrent covers this line is about, in the STRUCTURED fields only: the
        # sentence keeps saying "slide 1" because slide 1 is the slide being bought, and a console
        # line that started naming candidates would be describing an internal fan-out to an
        # operator who asked for a deck.
        whose = {"candidate": key[1]} if isinstance(key, tuple) else {}
        if env.halted or env.credits_exhausted:
            env.log.warn(
                "image_job_resubmit_skipped",
                f"{self.entry.asset_id} slide {number}: {cause} — the run stopped ordering work, "
                "so FR-317's one resubmit is not taken and the slide is lost",
                asset_id=self.entry.asset_id, slide=number, cause=cause, **whose)
            return outcome
        self.resubmitted.add(key)  # one-shot, before the await: no path may take it twice
        env.log.warn(
            "image_job_resubmit",
            f"{self.entry.asset_id} slide {number}: {cause} "
            f"({outcome.fail_message or 'no usable result'}) — resubmitting the SAME job once "
            "(FR-317, attempt 2 of 2); a second failure is final",
            asset_id=self.entry.asset_id, slide=number, cause=cause, attempt=2,
            task_id=outcome.task_id, detail=outcome.fail_message, **whose)
        again = await self._submit(prompt, urls, kind="discretionary", priority=priority,
                                   lost=lost, label=f"resubmit · slide {number}")
        return again if again is not None else outcome

    async def _submit(
        self, prompt: str, urls: list[str], *, kind: ReserveKind, priority: RenderPriority,
        label: str, lost: bool = True,
    ) -> RenderOutcome | None:
        """One submission through the caller's money door, and the three ways nothing was ordered.

        All three return `None` — no outcome joins `self.outcomes`, because none of them cost
        anything — but they are three different sentences to the operator, and the audit found the
        deck saying "declined by the spend cap" for two of them:

        * the 402 (`KieOutOfCredits`): the balance is gone, run-wide (FR-167);
        * the CAP declining discretionary spend (FR-106c): there is money, just not for this;
        * the RUNWAY declining it (`NO_RUNWAY`, D51): there is money and no clock. Nothing was
          reserved and nothing reached Kie, so it is not a failed render either — filing it as one
          would put a $0 job with no taskId in `self.outcomes` and in the meta's job list.
        """
        try:
            # FR-342: the render tier comes from the ONE accessor the Confirm-gate estimator also
            # read (`budget._image_price`), so a slide is submitted at exactly the tier its price
            # was approved at. `profiles._image_resolution` upper-cases it and clamps per ratio.
            outcome = await self.submit(
                self.entry, RenderParams(
                    prompt=prompt, aspect_ratio=self.entry.aspect_ratio,
                    resolution=self.env.config.image_resolution(self.entry.platform)),
                RenderRefs(image_urls=list(urls)), job="slide", priority=priority, kind=kind,
                label=label)
        except render.KieOutOfCredits as exc:
            self.env.credits_exhausted = True  # FR-167: latched once, for the whole run
            self._note(f"{label}: {_CREDITS} ({exc})", lost=lost)
            return None
        if outcome is None:
            self._note(f"{label}: declined by the spend cap (FR-106c)", lost=lost)
            return None
        if outcome.fail_cause is RenderFailCause.NO_RUNWAY:
            self.starved = True
            refusal = outcome.fail_message or "no_runway — no time left before the run deadline"
            self._note(f"{label}: {refusal} — nothing was ordered and nothing was billed",
                       lost=lost)
            return None
        self.outcomes.append(outcome)
        return outcome

    # ------------------------------------------------------------------- the gauntlet (D49)

    async def _anchor_gate(self) -> None:
        """FR-95/D49: judge slide 1 alone, and fix it once, before any slide is ordered to copy it.

        Spec §1: there is NO separate anchor entry point — this is `run_single` with a replaced
        config and the `brief` + `craft` critics. `system` is dropped because its whole subject is
        cross-frame consistency and a deck of one has none.

        TWO rounds, which is FR-324's "one extra round of re-renders, on the deck budget" spelled
        as the loop counts them: round 1 judges, the fix loop re-renders the cover once, round 2
        judges the replacement, and that is the ceiling (spec §2 breaks before the fix when
        `round == rounds_max`). The code shipped `rounds_max=1` and thereby forbade the one
        re-render the PRD grants — the 2026-08-14 live run blocked a whole deck on a missing page
        counter, a single-defect, entirely fixable cover, having never bought the render that would
        have fixed it. A cover is the cheapest frame in the deck to repair and the most expensive
        one to get wrong, so the round that repairs it is bought here rather than skipped.

        `rounds_max_image` is replaced too, and deliberately: `run_single` takes the MINIMUM of the
        two (a lone frame that needs three rounds is a copy problem), so a config that gates
        standalone images at one round — the shipped default — would silently take the pre-gate's
        fix round back. The spec pins the anchor's own ceiling, and replacing both is what makes it
        the value in force.

        What this call buys beyond the fix is the EARLY REFUSAL: a BLOCKED cover means the deck is
        unpublishable before a single body page has been bought. Every slide 2..N would copy that
        cover's template, its palette and, in the case the leakage tier exists for, its leaked mark
        or handle. Stopping here saves N renders on a deck nobody will ever see; a cover that merely
        fails on contract or craft is not stopped, because the deck-level loop that follows has
        rounds to fix it in.
        """
        if not self._gate or self.doomed or 1 not in self.delivered:
            return
        cfg = replace(self.env.config.run.gauntlet, rounds_max=2, rounds_max_image=2,
                      critics={name: critic
                               for name, critic in self.env.config.run.gauntlet.critics.items()
                               if name in ("brief", "craft")})
        report = await self._run(cfg, [1], RenderPriority.WAVE1, single=True)
        blocked = report.result == "blocked"
        self.env.log.event(
            "gauntlet_anchor", f"{self.entry.asset_id}: anchor pre-gate {report.result}"
            + (f"; slides 2-{len(self.texts)} are NOT ordered — the whole deck would copy this "
               "cover (FR-325)" if blocked
               else f"; slides 2-{len(self.texts)} are ordered next"),
            asset_id=self.entry.asset_id, result=report.result, rerenders=report.rerenders,
            critic_cost_usd=round(report.critic_cost_usd, 6),
            rerender_cost_usd=round(report.rerender_cost_usd, 6))

    async def _gauntlet(self) -> None:
        """The whole deck through the critic panel, fix loop included (spec §2).

        ONE call per critic per round covers every delivered slide, so an eight-slide deck costs
        three calls a round rather than twenty-four. Missing slides are not judged: a frame that was
        never delivered has no pixels to look at, and listing it would earn a `missing_text` verdict
        for a slide the deck already reports as missing.

        Nothing runs once the deck is unsalvageable (D51). A critic call is metered LLM spend and a
        fix is another render; buying either for a deck that will never be published is the exact
        waste the viability gate exists to stop, and "further work" there means the analysis as much
        as the pixels.
        """
        if not self._gate or self.doomed or self._blocked or not self.delivered:
            return
        await self._run(self.env.config.run.gauntlet, sorted(self.delivered),
                        RenderPriority.WAVE2, single=False)

    async def _run(self, cfg: Any, numbers: list[int], priority: RenderPriority, *,
                   single: bool) -> gauntlet.GauntletReport:
        """One gauntlet call — deck or anchor — with this deck's contract and money seam.

        Both reports land on `self.report`: the deck's overwrites the anchor's, because the deck
        run judged slide 1 again as part of the set and its rounds are the ones `meta.yaml` should
        carry. The anchor's spend is carried forward rather than lost, so `meta.yaml.gauntlet`'s two
        cost fields are the deck's WHOLE gauntlet bill and not merely its second half.
        """
        env = self.env
        frames = [gauntlet.FrameUnderTest(number=n, source=self._input(n)) for n in numbers
                  if self._input(n)]
        if not frames:
            return gauntlet.GauntletReport(result="skipped")
        contract = self._contract(numbers)
        rerender = self._fix_render(priority)
        call = gauntlet.run_single if single else gauntlet.run_deck
        report = await call(frames[0] if single else frames, contract, rerender,  # type: ignore[arg-type]
                            cfg=cfg, call=env.llm_call, log=env.log, engine=env.engine)
        before = self.report
        if before is not None:  # the anchor pre-gate's bill is part of this deck's gauntlet bill
            report.critic_cost_usd += before.critic_cost_usd
            report.rerender_cost_usd += before.rerender_cost_usd
            report.rerenders += before.rerenders
            report.degraded_gate = report.degraded_gate or before.degraded_gate
        self.report = report
        return report

    @property
    def _gate(self) -> bool:
        """D49: the post-render gate is on AND a metered LLM call exists to run it with."""
        return contracts.gate_on(self.env)

    @property
    def _blocked(self) -> bool:
        """Has the gate already refused this deck? Nothing further is ordered for it (FR-325)."""
        return self.report is not None and self.report.result == "blocked"

    def _contract(self, numbers: Sequence[int]) -> gauntlet.DeckContract:
        """What these frames were ORDERED to be — the referent every verdict is judged against.

        Assembled from the same values the render prompts were assembled from: the slide's verbatim
        text, its counter, slide 1's wordmark, the D-A sanction list, the style's DNA and zones. The
        FORBIDDEN side (FR-330) is the expensive half and is built from three sources — the
        competitor list this deck's prompts already suppress, the source creator's identity in every
        spelling the payload offers (FR-312), and every mark the sanction gate refused.
        """
        facts = contracts.panel_facts(self.env, self.entry)
        frames = [
            contracts.frame_contract(
                number, self.texts[number - 1] if 1 <= number <= len(self.texts) else "",
                style=self.style, counter=self._counter(number),
                # M12: the deck is signed on the anchor alone, so the signature is slide 1's own
                # and every other frame lists none — an unlisted wordmark reads as invented text,
                # and a listed one nobody ordered reads as a missing string.
                signature=self.wordmark if number == 1 else "",
                wordless_reason=facts.get(number, {}).get("wordless_reason", ""),
                truncation_suspect=bool(facts.get(number, {}).get("truncation_suspect")))
            for number in numbers]
        sanctioned = [name for number in numbers for name in self._sanctioned_marks(number)]
        return contracts.deck_contract(
            frames, entry=self.entry, style=self.style, wordmark=self.wordmark,
            counter=self._counter(1),
            required_marks=list(dict.fromkeys(sanctioned)),
            forbidden=contracts.forbidden_terms(
                competitors=self._competitors,
                creator_forms=contracts.creator_forms(self.source_post),
                unsanctioned_marks=self._unsanctioned_marks(numbers),
                sanctioned=sanctioned))

    def _unsanctioned_marks(self, numbers: Sequence[int]) -> list[str]:
        """Every brand mark the source panels showed that D-A REFUSED to sanction (FR-330).

        The sanction gate already decided these may not be drawn — a competitor, the creator's own
        logo, platform chrome — so a render that drew one anyway is precisely the leakage the
        `brief` critic exists to catch, and naming them is what lets it. Read off the same
        intelligence `_sanctioned_marks` reads, so the two lists partition one set rather than
        describing two.
        """
        intel = self._intel()
        allowed = {name.casefold() for number in numbers
                   for name in self._sanctioned_marks(number)}
        out: list[str] = []
        for number in numbers:
            slide = intel.slide(number) if intel is not None else None
            for raw in list(getattr(slide, "brand_marks", ()) or ())[:_MAX_MARKS_READ]:
                name = mark_name(str(raw or ""))
                if name and name.casefold() not in allowed and name not in out:
                    out.append(name)
        return out

    def _fix_render(self, priority: RenderPriority) -> gauntlet.RerenderFn:
        """The MONEY SEAM (spec §1): one fix-loop re-render, and the six ways it does not happen.

        The gauntlet owns the loop and this closure owns every dollar in it. In order, because the
        order is the point — each refusal below is free, and the cheapest refusal comes first:

        * `env.halted` — Ctrl+C or the deadline. Nothing new is ordered (FR-201/108) -> `halted`,
          which the gauntlet reads as a deadline stop.
        * exhausted credits or an unsalvageable deck -> `failed`: there is nothing to buy and
          nothing to buy it for.
        * the PER-DECK cap (`run.gauntlet.deck_budget_usd`) -> `declined_deck_budget`. RESERVED
          before the submit and settled after it (F4), so the cap is a ceiling on what this deck
          can spend rather than a description of what it already has — and one every concurrent
          re-render of the same round measures against the same claimed total.
        * D51's RUNWAY -> `declined_runway`. A ten-minute job with four minutes of deadline left is
          a purchased certainty of a timeout, and this refusal costs nothing.
        * the RUN cap declining the discretionary reserve (FR-106c) -> `declined_budget`.
        * anything the provider did to the job itself -> `failed`, and the frame keeps its standing
          defects into the terminal policy.

        FR-317 exclusivity (spec §7) is structural: this goes through `_submit`, NOT `_call`, so a
        fix re-render is a FRESH submission with its own ledger rows that is never itself
        resubmitted and never gets a second poll window. `lost=False` throughout — the slide being
        improved is already on disk, so nothing here can put it in the missing-slide ledger.
        """
        async def rerender(number: int, fix: str) -> gauntlet.RerenderResult:
            env = self.env
            if env.halted:
                return gauntlet.RerenderResult(status="halted")
            if env.credits_exhausted or self.doomed:
                return gauntlet.RerenderResult(status="failed")
            projected = self._projection()
            if not await self._claim(projected, number):
                return gauntlet.RerenderResult(status="declined_deck_budget")
            billed = 0.0
            try:
                if not self._runway():
                    return gauntlet.RerenderResult(status="declined_runway")
                anchor = self.anchored and number != 1
                refs = await self._refs(number, anchor, rerender=True)
                prompt = self._prompt(number, anchor=anchor, refs=refs, fix=fix)
                if prompt is None:
                    return gauntlet.RerenderResult(status="failed")
                starved = self.starved
                outcome = await self._submit(
                    prompt, [ref.url for ref in refs], kind="discretionary", priority=priority,
                    lost=False,
                    label=f"gauntlet re-render · slide {number} · {self.entry.asset_id}")
                if outcome is None:
                    return gauntlet.RerenderResult(
                        status="declined_runway" if self.starved and not starved
                        else "declined_budget")
                billed = float(outcome.cost_usd or 0.0) or projected
                stored = await self._store(number, outcome, lost=False)
                if not stored:
                    return gauntlet.RerenderResult(status="failed", cost_usd=billed)
                self.rerendered.add(number)
                return gauntlet.RerenderResult(
                    status="delivered", cost_usd=billed,
                    frame=gauntlet.FrameUnderTest(number=number, source=self._input(number)))
            finally:
                # Every path out of the claim — the four refusals, the delivery, an exception
                # nobody here expects — gives the reservation back and accrues what was actually
                # billed. A `finally` rather than a line per branch because a leaked claim is a
                # deck refusing its own next fix over money it never spent, and there are five
                # returns to leak it from.
                await self._settle(projected, billed)

        return rerender

    async def _claim(self, projected: float, number: int) -> bool:
        """F4: hold `projected` against `run.gauntlet.deck_budget_usd`, or refuse the re-render.

        The pattern is `Budget.reserve`'s, one scope down (`budget.py`): decide and debit under one
        lock, so concurrent callers can never jointly exceed the cap. It has to be, because the
        gauntlet re-renders a round's failing frames CONCURRENTLY — the 2026-08-14 run gathered
        eleven of them, every one read `gauntlet_spend` before any of them had accrued, and eleven
        $0.03 jobs shipped against a $0.30 cap. Checking a number that only moves after the awaits
        have finished is not a cap; it is a description of the previous round.

        The projection is the same figure the money door prices the submission with
        (`_projection`), and it is what is HELD; `_settle` swaps it for the provider's own figure
        once the job comes back. A cap of `0` (or an absent one) is off, as before, and a caller
        with no `price_job` seam projects `$0`, which claims nothing and refuses nothing.

        Returns:
            True when the money is claimed and the caller may submit; False when the cap refuses
            it — nothing is held in that case, and the caller owes no settlement it did not make.
        """
        cap = float(getattr(self.env.config.run.gauntlet, "deck_budget_usd", 0.0) or 0.0)
        async with self.gauntlet_lock:
            if cap > 0 and self.gauntlet_spend + self.gauntlet_reserved + projected > cap:
                self.env.log.warn(
                    "gauntlet_budget_stop",
                    f"{self.entry.asset_id} slide {number}: the per-deck gauntlet budget "
                    f"({cap:.2f}) is spent ({self.gauntlet_spend:.2f} billed, "
                    f"{self.gauntlet_reserved:.2f} claimed by re-renders still in flight) — no "
                    "further fix re-render is ordered for this deck "
                    "(run.gauntlet.deck_budget_usd)",
                    asset_id=self.entry.asset_id, slide=number, spent_usd=self.gauntlet_spend,
                    reserved_usd=self.gauntlet_reserved, projected_usd=projected, cap_usd=cap)
                return False
            self.gauntlet_reserved += projected
            return True

    async def _settle(self, projected: float, billed: float) -> None:
        """F4's other half: release the claim and accrue what the provider actually charged.

        Under the same lock as `_claim`, and never below zero — a float that drifted a claim into
        `-0.0000001` would make the next round's arithmetic marginally generous, which is exactly
        the failure mode this pair exists to close. `billed` is `0.0` for every path that never
        reached a submission, so a declined or failed re-render costs the deck its claim back and
        nothing else.
        """
        async with self.gauntlet_lock:
            self.gauntlet_reserved = max(0.0, self.gauntlet_reserved - projected)
            self.gauntlet_spend += billed

    def _projection(self) -> float:
        """What ONE more slide render costs, asked of the money door rather than computed here.

        `Env.price_job` is the same `budget.job_projection` the metered `submit` prices every
        submission with, exposed as a seam precisely so this module can measure a per-deck ceiling
        without importing `budget` or touching `env.budget` — the module contract above stands.
        A caller that wires no seam (a preview, a unit test) projects `$0`, which turns the per-deck
        cap into a no-op rather than into a silent refusal of every fix.
        """
        price = getattr(self.env, "price_job", None)
        return float(price(self.entry, "slide") or 0.0) if callable(price) else 0.0

    def _runway(self) -> bool:
        """D51 before the submit, not after it: has the clock room for one more image job?

        Asked of `Env.runway_ok`, the same predicate the metered door enforces, so a fix re-render
        and a first-pass slide answer the question identically. `True` with no seam wired: a run
        with no deadline has infinite runway by definition (previews, unit tests).
        """
        ok = getattr(self.env, "runway_ok", None)
        return bool(ok("slide")) if callable(ok) else True

    # --------------------------------------------------------------------------------- inputs

    async def _refs(self, number: int, anchor: bool, *,
                    rerender: bool = False) -> list[Reference]:
        """Slide 1 leads for slides 2–N (FR-95 PRIMARY), a re-render also gets its nearest
        delivered NEIGHBOUR, then the brief's photos, then FR-315's mark patches, then the hard cap.

        Order is the contract: the anchor is `Image 1` and outranks everything (FR-190 rewrites its
        role line from `carousel_anchor_instruction.md` over position 0), the neighbour sits
        immediately under it, and the patches come last because they are the narrowest attachments
        in the set — one logo each, contributing nothing but their own pixels. The cap is the
        provider's, applied once at the end, so a deck with a photo-heavy brief loses patches
        rather than losing its anchor.

        The neighbour is a RE-RENDER's reference and only a re-render's (FR-323/FR-18 as amended
        v2.2.0). A first pass is chained to the cover by design and a deck of slides each copying
        the slide before it would drift by construction; a slide being rendered a second time,
        however, is being fitted back INTO a deck that already exists around it, and the cover
        alone is a poor description of what page four looks like. It is one of our own rendered
        artifacts (D46-compatible — never a source byte), and it costs nothing: the URL is already
        held.
        """
        refs = ([Reference(self.anchor_url, _ANCHOR_ROLE), *self.attached]  # role -> ROLE_ANCHOR
                if anchor and self.anchor_url else list(self.attached))
        if rerender and (neighbour := await self._neighbour_ref(number)) is not None:
            refs.insert(1 if anchor and self.anchor_url else 0, neighbour)
        refs.extend(self._patch_refs(number))
        return refs[:self._limit]

    async def _neighbour_ref(self, number: int) -> Reference | None:
        """The nearest ALREADY DELIVERED slide, as a look-and-layout reference, or `None`.

        Nearest by distance, earlier slide winning a tie — the page before is the page a reader
        sees immediately before this one, so it is the stronger continuity claim. The anchor is
        excluded: it is already attached in its own right on a chained deck, and the whole value of
        this reference is that it is NOT the cover.

        Prefers the provider URL we are already holding and falls back to uploading the delivered
        file (`refs.upload_local`, which is memoised per run) when there is none to hold — a slide
        stored from a URL that has since expired, or a deck long enough that Kie's ~24 h window
        matters. A failed upload costs the reference and nothing else: the re-render still carries
        the anchor, the brief's photos and its patches, exactly as it did before this existed.
        """
        candidates = sorted((n for n in self.delivered if n not in (number, 1)),
                            key=lambda n: (abs(n - number), n > number))
        for near in candidates:
            url = self.urls.get(near, "")
            if not url and (path := self.paths.get(near)) is not None:
                url = await upload_local(path, self.env,
                                         label=f"{self.entry.asset_id} slide {near} neighbour ref")
            if url:
                return Reference(url, _NEIGHBOUR_ROLE.format(number=near))
        return None

    def _patch_refs(self, number: int) -> list[Reference]:
        """FR-315: this slide's sanctioned marks that have pixels, as MARK PATCH references.

        The join is on the SANCTION list, never on the patch table: a mark whose patch exists but
        whose name was filtered out (a competitor, the creator's own logo, platform chrome) must
        not reach the job through the back door of having been croppable. Marks with no patch are
        not an error — they ride as names in the prompt's TOOL MARKS line exactly as before — and
        the split is logged per slide so a review of a wrong logo can tell which of the two paths
        drew it.
        """
        sanctioned = self._sanctioned_marks(number)
        if not sanctioned:
            return []
        # BOTH sides of the join run the same two functions in the same order (v2.1.4). The patch
        # table is keyed `collapse(mark_name(box_name))` at upload; matching a sanctioned name
        # with `collapse` alone made the join depend on the two strings having been *written* the
        # same way, and in glz0 they were not — box `"Claude"`, sanctioned `"Claude logo/wordmark"`,
        # no match, no patch, a recoloured logo. `mark_name` is idempotent, so applying it to an
        # already-cleaned name is free and the symmetry is now structural rather than incidental.
        keys = {name: collapse(mark_name(name)) for name in sanctioned}
        refs = [Reference(self.patches[keys[name]], _MARK_PATCH_ROLE.format(name=name))
                for name in sanctioned if keys[name] in self.patches]
        self.env.log.event(
            "mark_patches_attached",
            f"{self.entry.asset_id} slide {number}: {len(refs)} of {len(sanctioned)} sanctioned "
            f"mark(s) ride as cropped patches", verbose_only=True, asset_id=self.entry.asset_id,
            slide=number, patched=[name for name in sanctioned if keys[name] in self.patches],
            name_only=[name for name in sanctioned if keys[name] not in self.patches])
        return refs[:_MAX_MARK_PATCHES]

    def _prompt(self, number: int, *, anchor: bool, refs: list[Reference],
                fix: str = "") -> str | None:
        """One slide's finished prompt, or `None` when it cannot be filled (FR-260).

        `fix` is the gauntlet's canned remedy suffix on a fix-loop re-render (FR-323) and `""`
        otherwise. It goes through the ENGINE's `suffix` rather than being appended afterwards,
        because the provider measures the whole string: three glz0 retry prompts were built by
        appending a block to a prompt already at the limit, and each bought an HTTP 500.

        The TEXT is identical on both passes, and so is the RULEBOOK around it (F1-C): the fix
        suffix's room is reserved on every pass, so a re-render is assembled against exactly the
        body budget its first render had. A gauntlet re-render changes the REQUEST, never the
        words: the strings are locked contract strings (FR-304 — a verbatim quote of the source
        panel, or its D54-compressed text) and the fix channel is removal-side and layout-side by
        construction.
        """
        env = self.env
        copyset = self.copy
        text = self.texts[number - 1]
        if copyset is not None and not text.strip():
            # FR-304: a wordless source panel renders wordless. `prompts_engine._onimage_text`
            # falls back to `copy.headline` when a carousel slide's text is empty (`slide_text or
            # headline`) — the last repeat path left in the deck — so this slide's context gets a
            # headline-free copy of the CopySet. A local blanking, not a mutation: the deck's own
            # copy is what the caption and every other slide still read.
            copyset = replace(copyset, headline="")
        urls = [ref.url for ref in refs]
        try:
            roles = role_lines(refs)  # FR-191: one line per attachment, by provenance
            if anchor and urls:  # FR-190: the anchor block outranks every role under it
                roles[0] = env.engine.render(ROLE_ANCHOR, {},
                                             profile=env.config.models.image_profile)
            context = build_context(
                trend=env.trends.get(self.entry.trend_key or ""), style=self.style,
                copy=copyset, creative_format="carousel", niche_descriptor=env.niche_descriptor,
                # FR-144/145, allowlisted for `carousel_slide.md`; read through `getattr` because
                # this module targets the duck-typed Env surface, not its dataclass.
                campaign_brief=getattr(env, "campaign_briefs", {}).get(
                    self.entry.brief_name or ""),
                niche_visual_world=getattr(env, "niche_visual_world", ""),  # A15, same seam
                # M6 (W3): config blocklist + this topic's guarded LLM strips — read through
                # `getattr` like every Env read here (this module targets the duck-typed surface).
                competitor_strings=self._competitors,
                # M12: an anchored slide 2–N inherits the signature from the picture it reproduces,
                # so the branding block rides the anchor alone; an independently generated deck
                # (`carousel_anchor: false`, or the FR-95 fallback) needs it on every slide.
                branding_block=self.branding if number == 1 or not anchor else "",
                # M12, the strict half: the WORDMARK is slide 1's alone, whatever the deck's
                # shape. A deck signed once reads as designed; signed N times it reads as a
                # watermark, and `carousel_anchor_instruction.md` tells slides 2–N never to refill
                # the signature zone.
                wordmark=self.wordmark if number == 1 else "",
                # D-D, and deliberately NOT gated like the wordmark above: a page badge belongs on
                # every page or on none. Slide 1 signs the deck; slide 1..N each state their own
                # place, in the source's hand, over OUR length. Empty when nothing was detected,
                # which is what makes the template state the absence instead.
                slide_counter=self._counter(number),
                text_budgets=env.config.run.text_budgets,
                reference_roles=roles,
                slide_index=f"{number} of {len(self.texts)}",  # 50 §6's fill convention
                slide_text=text,
                # D46 (FR-304/FR-308): the two panel-mapping slots — both empty for unbound or
                # brief-driven decks, and the template's "(ignore if empty)" lines stay silent.
                visual_brief=self._visual_brief(number),
                slide_panel_source=self._panel_source_line(number),
                # D-A: the real logos THIS panel showed, filtered and cleaned. Empty is the norm
                # and means the pre-D-A rule — every mark stays a generic unlettered shape.
                tool_marks=", ".join(self._sanctioned_marks(number)))
            context["style_dna"] = self.dna  # FR-189: the one block that never varies
            context["render_prompt"] = self._guided(context["render_prompt"], number)
            prompt = env.engine.render(
                ROLE_SLIDE, context, profile=env.config.models.image_profile,
                max_chars=self._prompt_cap(fix),  # 50 §7, with F1-C's fix reservation
                suffix=fix)
        except (UnresolvedPlaceholderError, MissingTemplateError, ValueError, LookupError) as exc:
            env.log.error("prompt_assembly_failed", f"{self.entry.asset_id} slide {number}: {exc}",
                          asset_id=self.entry.asset_id, slide=number, role=ROLE_SLIDE)
            return None
        env.log.event("render_prompt_assembled",
                      f"{self.entry.asset_id} slide {number}/{len(self.texts)}"
                      f"{self._panel_note(number)} ready",
                      verbose_only=True, asset_id=self.entry.asset_id, slide=number,
                      source_panel=number if self.source_post is not None else None,
                      onimage_text=bool(text.strip()),
                      references=len(urls), retry=bool(fix), prompt=prompt)
        return prompt

    def _guided(self, render_prompt: str, number: int) -> str:
        """The style's instruction for THIS slide's role — cover for slide 1, body for the rest.

        M9's home for cover-vs-body divergence: `style_dna` must be byte-identical across the deck,
        so the one legitimate difference between a cover and a page lives in `per_format_guidance`
        and is appended to the style's own `render_prompt`. Nothing is appended under an override
        brief (`self.style` is then None and `render_prompt` is the brief's own directives, FR-144)
        or for a style that declares no guidance for this role — a deck of one grammar is the
        registry's stated intent, not an omission to paper over.
        """
        if self.style is None:
            return render_prompt
        key = GUIDANCE_COVER if number == 1 else GUIDANCE_SLIDE
        guidance = self.style.per_format_guidance.get(key, "").strip()
        return f"{render_prompt} {guidance}".strip() if guidance else render_prompt

    # ------------------------------------------------------------------------------ packaging

    def package(self) -> AssetRecord:
        """Terminal meta: what shipped, what it cost, which slides are missing (FR-73/74)."""
        entry, env = self.entry, self.env
        missing = [n for n in range(1, len(self.texts) + 1) if n not in self.delivered]
        fields: dict[str, Any] = {
            "actual_cost_usd": round(sum(o.cost_usd for o in self.outcomes), 6),
            # FR-270, honestly (v2.1.4): a deck routinely uses BOTH gpt-image-2 routes — an
            # unreferenced cover goes text-to-image, every anchored body slide goes
            # image-to-image (FR-241) — so it records the ids of the routes its slides actually
            # took. Recording `models.image` alone claimed a text-to-image render for the
            # reference-bearing slides that are most of a deck.
            "model_ids": [*self._route_ids(), env.config.models.image_profile],
            "kie_job_ids": [o.task_id for o in self.outcomes if o.task_id],
            "job_submission_timestamp": next(
                (o.submitted_at for o in self.outcomes if o.submitted_at), None),
            "job_completion_timestamp": next(
                (o.completed_at for o in reversed(self.outcomes) if o.completed_at), None),
            # FR-98: shipped as it came back, and recorded as it came back — the first delivered
            # slide's own header, not the ratio the deck asked for (audit R4: a 1536x1024 anchor
            # was filed as `1:1`). One measurement per deck; every slide of a deck is one job
            # shape, and a per-slide read would buy N warnings about the same provider answer.
            "native_size_rendered": self._native_size(),
            "slide_count": len(self.delivered),
            # FR-321: what the deck was ORDERED to be, beside what it delivered. `slide_count`
            # alone reads as a complete deck of that length in every downstream surface — a 7 is a
            # 7 whether eight were ordered or seven were. Recording both makes "7 of 8" the
            # machine-readable fact the spend table and the gallery header then state.
            "slides_ordered": len(self.texts),
            "missing_slide_numbers": missing,
            # FR-313 (v2.5.0, D59): the counter receipt — whether this deck renders a position
            # badge, which accept rule believed it, and what slide 1's badge reads. Detected once
            # in `__post_init__`, so this only reports it.
            "counter": self._counter_meta(),
            # FR-351 (v2.6.0, D62): the cover best-of-N receipt — which candidates were bought,
            # which one anchors the deck and in whose words. `None` on every deck that never fanned
            # out, which is the whole pre-D62 world and every `cover_candidates: 1` run after it.
            "cover_pick": self.cover_pick,
            # FR-328 (spec §6): the gate's own receipt, on EVERY terminal path it touched — pass,
            # blocked, degraded, budget stop, deadline stop. `None` when the gate never ran.
            "gauntlet": contracts.report_meta(self.report),
            # The same verdict in FR-27's four-state vocabulary, which the gallery badge, the spend
            # surfaces and a Phase-2 publisher all read (see `contracts.verdict_result`).
            "vision_check_result": contracts.verdict_result(
                self.report, rerendered=bool(self.rerendered)),
        }
        if self.report is not None:  # the operator-readable critic record, beside the artifacts
            self.folder.write_gauntlet_report(
                contracts.report_rows(self.report, asset_id=entry.asset_id))
        if self.doomed and self.delivered:
            # D51: the deck rendered slides and can still never ship as the deck that was approved.
            # It is a FAILURE that keeps every paid artifact (FR-74) — the operator can open the
            # folder and see what was bought — and it is deliberately not `incomplete`, because
            # `incomplete` means "this partial deck ships" and this one does not.
            reason = (f"deck_viability_loss: {self.doomed} — a carousel is our slide i for their "
                      f"panel i (FR-304), so a slide lost to a render defect cannot be shipped "
                      f"around; {len(self.delivered)} paid slide(s) are kept but the deck is not "
                      f"published (D51)")
            entry.status = PlanEntryStatus.FAILED
            entry.skip_reason = entry.skip_reason or reason
            fields["event_id"] = env.log.error(
                "deck_viability_loss", f"{entry.asset_id}: {reason}", asset_id=entry.asset_id,
                delivered=sorted(self.delivered), missing_slide_numbers=missing,
                cost_usd=fields["actual_cost_usd"],
                # EVERY loss, like `carousel_incomplete`'s field and for the same reason: the
                # numbers and their explanations are two halves of one line and must agree.
                detail="; ".join(self.reasons))
            return self.folder.skip(reason, DECK_VIABILITY_LOSS, **fields)
        if not self.delivered:
            reason = "; ".join(self.reasons[:3]) or "carousel produced no slides"
            entry.status = PlanEntryStatus.ABANDONED if self.abandoned else PlanEntryStatus.FAILED
            entry.skip_reason = entry.skip_reason or reason
            tag = DegradationTag.ABANDONED if self.abandoned else (
                DECK_VIABILITY_LOSS if self.doomed else None)
            return self.folder.skip(reason, tag, **fields)
        if self.report is not None and self.report.result == "blocked":
            # FR-325: the deck RENDERED — every slide is on disk and every dollar is spent — and a
            # standing defect the fix loop could not clear means it is not published. Deliberately
            # neither `finish()` nor `skip()`: `skip()` means "this creative did not happen", and
            # this one happened in full. `PlanEntryStatus.BLOCKED` is a non-success everywhere
            # success matters — the trend-history window does not burn this deck's source post, the
            # `latest` pointer is not claimed on its account, and the run exits 1.
            reason = ("gauntlet_blocked: the post-render critic panel found standing defect(s) "
                      f"after {len(self.report.rounds)} round(s) and {self.report.rerenders} "
                      "re-render(s); every paid slide is kept and nothing is published (FR-325). "
                      "See BLOCKED.txt and GAUNTLET_REPORT.yaml")
            entry.status = PlanEntryStatus.BLOCKED
            entry.skip_reason = entry.skip_reason or reason
            fields["event_id"] = env.log.error(
                "gauntlet_blocked", f"{entry.asset_id}: {reason}", asset_id=entry.asset_id,
                slides=len(self.delivered), rounds=len(self.report.rounds),
                rerenders=self.report.rerenders, cost_usd=fields["actual_cost_usd"],
                critic_cost_usd=round(self.report.critic_cost_usd, 6),
                rerender_cost_usd=round(self.report.rerender_cost_usd, 6))
            return self.folder.block(reason, contracts.blocked_text(self.report), **fields)
        if self.report is not None and self.report.craft_only:
            # FR-325 tier 3: the only standing failures are craft OPINIONS about quality. The deck
            # ships and says so — `cfg.craft_blocks: true` is what turns this into the branch above.
            self.folder.mark(GAUNTLET_CRAFT)
        if self.report is not None and (self.report.degraded_gate
                                        or self.report.result == "degraded"):
            # Every degraded ship carries the tag (fixed 2026-08-20, live gap found the day
            # `fail_action: degrade` became the shipped policy). Causes: D3 (a critic that could
            # not be parsed was dropped, gate thinner than configured), FR-325's cosmetic /
            # low-confidence / final-round-grace demotions (degraded_gate), and a contract-tier
            # `fail_action: degrade` outcome (result alone — degraded_gate stays False there so
            # the console can still tell the causes apart). Either way the deck ships and the
            # tag is what stops that reading as a clean pass.
            self.folder.mark(GAUNTLET_DEGRADED)
        if missing:  # 10 §10: completed slides ship, the deck says which ones did not
            self.folder.mark(DegradationTag.INCOMPLETE)
            env.log.warn("carousel_incomplete",
                         f"{entry.asset_id}: {len(self.delivered)}/{len(self.texts)} slides "
                         f"delivered; missing {missing}", asset_id=entry.asset_id,
                         # EVERY loss, not the first three. `missing_slide_numbers` beside this
                         # field already enumerates all of them, so a capped `detail` made the two
                         # halves of one line disagree: six numbers, three explanations, and no
                         # way to tell which three lost slides went unexplained. This is a
                         # structured log field, not a console line — it has no width to protect.
                         missing_slide_numbers=missing, detail="; ".join(self.reasons))
        entry.status = PlanEntryStatus.SUCCESS
        fields["event_id"] = env.log.event(
            "creative_delivered", f"{entry.asset_id} deck of {len(self.delivered)} slide(s)",
            asset_id=entry.asset_id, slides=len(self.delivered),
            cost_usd=fields["actual_cost_usd"],
            gauntlet=(self.report.result if self.report is not None else "not_run"),
            vision_check=fields["vision_check_result"].value)
        return self.folder.finish(**fields)

    def _route_ids(self) -> list[str]:
        """The configured id of every gpt-image-2 route this deck's slides really used (FR-241).

        Observed, not assumed: `_slide` records whether each submission carried references, so a
        deck that anchored records both ids and a deck whose every slide went out reference-free
        records one. Order is stable (reference-free first) so two runs of the same shape produce
        the same meta line.
        """
        models = self.env.config.models
        return [route for route, used in ((models.image, self.text_route),
                                          (models.image_edit, self.edit_route)) if used] or [
            models.image]

    def _native_size(self) -> str:
        """FR-98's `native_size_rendered` for the deck — measured off the first delivered slide.

        Falls back to the requested ratio when nothing was delivered or the file cannot be read,
        which is the pre-v2.1.4 value: the field must never be empty, because the gallery prints
        it as the right-hand side of `ratio 1:1 → …`.
        """
        first = next((self.paths[n] for n in sorted(self.paths)), None)
        if first is None:
            return self.entry.aspect_ratio
        return native_size(first, self.entry.aspect_ratio, log=self.env.log,
                           asset_id=self.entry.asset_id, slide=min(self.paths))

    # -------------------------------------------------------------------------- small helpers

    @property
    def copy(self) -> CopySet | None:
        return self.env.copy.get(self.entry.asset_id)

    @property
    def source_post(self) -> SourcePost | None:
        """The slideshow post this deck was bound to at ASSIGN (FR-304), or None.

        None on two legitimate paths: an override brief binds no post at all (§0.14d), and a topic
        that is no longer in `env.trends` — a plan resurrected from a previous run's meta, say —
        leaves the join unresolved. Both mean the same thing here: no source deck to compare
        against, so no panel wording and no truncation tag.
        """
        post_id = str(self.entry.source_post_id or "")
        trend = self.env.trends.get(self.entry.trend_key or "") if post_id else None
        return next((post for post in getattr(trend, "posts", ()) or ()
                     if str(post.post_id) == post_id), None)

    def _length(self) -> int:
        """This deck's slide count — `entry.slide_count` under the platform ceiling (FR-95/§0.4′).

        ASSIGN already clamped it; the ceiling is re-applied here because generation may never
        outrun the number the Confirm gate priced, whatever wrote the entry. `_FALLBACK_SLIDES`
        covers a platform config that names no ceiling at all.
        """
        ceiling = (self.env.config.platform(self.entry.platform).carousel_slides
                   or _FALLBACK_SLIDES)
        return max(1, min(int(self.entry.slide_count or ceiling), ceiling))

    def _panel_note(self, number: int) -> str:
        """` (source panel i)` for a panel-mapped deck, `""` for a brief-driven one (FR-302).

        Slide *i* renders source panel *i* — the mapping is positional and never renumbered — so
        the label states the source position rather than a lookup nobody can verify from the log.
        """
        return f" (source panel {number})" if self.source_post is not None else ""

    def _intel(self) -> Any:
        """This deck's FR-306 slide intelligence, or `None` — duck-typed off the Env like every
        optional seam here, so a caller without the field (previews, older tests) renders the
        deck exactly as before, briefs simply absent."""
        if self.source_post is None:
            return None
        return getattr(self.env, "slide_intel", {}).get(self.entry.source_post_id or "")

    def _visual_brief(self, number: int) -> str:
        """FR-308/FR-316: the slide's English content directive, cleaned at the CHOKEPOINT.

        `""` whenever intelligence degraded — the `(ignore if empty)` line in the template makes
        that absence silent by design — and `""` for a WORDLESS slide, which is FR-316's rule and
        the sharper of the two. A panel our deck maps with no text is deliberately wordless; a
        brief describing what that panel showed is exactly the input that puts a headline, a label
        or an invented widget back onto it, and the slide's whole job is to carry nothing.

        Otherwise the brief passes the creator strip: the source author's identity may not travel
        into a render prompt in ANY spelling (FR-312's rule, applied here because this is the last
        place the brief is a string before it becomes a prompt). The competitor strip is downstream
        and unchanged — `prompts_engine.build_context` runs it over this value with every other
        context field, so this method deliberately does not repeat it.

        Cleaning at consumption rather than at production is the point: briefs written by an
        earlier run, an older prompt or a degraded call all pass through here, and one gate that
        every brief crosses beats a contract every producer has to remember (FR-316's
        defense-in-depth clause).
        """
        intel = self._intel()
        slide = intel.slide(number) if intel is not None else None
        brief = str(getattr(slide, "visual_brief", "") or "")
        if not brief.strip():
            return ""
        text = self.texts[number - 1] if 1 <= number <= len(self.texts) else ""
        if not text.strip():  # FR-316: a wordless slide gets a content-free brief
            self.env.log.event(
                "visual_brief_dropped_wordless",
                f"{self.entry.asset_id} slide {number}: the mapped panel carries no text, so its "
                "visual brief is not sent — a wordless slide may not have content re-invented onto "
                "it (FR-316)", verbose_only=True, asset_id=self.entry.asset_id, slide=number)
            return ""
        return self._scrub_creator(brief, number)

    def _scrub_creator(self, brief: str, number: int) -> str:
        """FR-316/FR-312: the source author's identity, out of the brief, however it was spelled.

        Matching is COLLAPSED — punctuation, spacing and case removed on both sides — because a
        vision pass transcribes one creator three ways in one deck: `@emirailab`, `Emir AI Lab`,
        `EMIR AI LAB`. Collapsed, all three are `emirailab`, and so is any sentence containing any
        of them. The unit dropped is the SENTENCE, not the token: "The Emir AI Lab logo sits top
        left" with only the name removed still directs a logo into the corner, which is the
        creator's signature by another route.

        An author string shorter than `_MIN_AUTHOR_IDENT` collapsed is not matched at all — a
        two-letter handle would swallow half of any English sentence, and a brief scrubbed to
        nothing is a slide that renders content-free for no reason.
        """
        ident = collapse(getattr(self.source_post, "author", "") or "")
        if len(ident) < _MIN_AUTHOR_IDENT:
            return brief
        kept = [part.strip() for part in _SENTENCE_SPLIT.split(brief)
                if part.strip() and ident not in collapse(part)]
        scrubbed = " ".join(kept)
        if scrubbed != brief.strip():
            self.env.log.warn(
                "visual_brief_creator_scrubbed",
                f"{self.entry.asset_id} slide {number}: the visual brief named the source creator "
                f"and was scrubbed before rendering (FR-316/FR-312); "
                f"{len(kept)} of {len(_SENTENCE_SPLIT.split(brief))} sentence(s) kept",
                asset_id=self.entry.asset_id, slide=number, author=ident)
        return scrubbed

    def _counter_spec(self) -> CounterSpec | None:
        """Did the SOURCE deck number its slides, and in what hand (D-D)? Detected once.

        Read off the slide intelligence, because that is where the source's chrome was transcribed
        — page counters live in `chrome_text` by design (§0.11 splits them away from the panel's
        words). A deck with no intelligence, no source post or no counted slides gets `None`, and
        `None` is a real answer: this deck renders with no badge and its prompt says so.
        """
        intel = self._intel()
        slides = list(getattr(intel, "slides", ()) or ()) if intel is not None else []
        if not slides:
            return None
        return detect_counter(
            [str(getattr(slide, "chrome_text", "") or "").splitlines() for slide in slides],
            [str(getattr(slide, "text", "") or "") for slide in slides],
            len(slides))

    def _counter_meta(self) -> dict[str, Any] | None:
        """FR-313's `meta.yaml.counter` for this deck — or `None`, because the question is moot.

        `None` on an override brief: it binds no source post (§0.14d/FR-144), so "did their deck
        number its slides" is a question about a deck that does not exist, and a `False` there
        would read as an answer. The gate is `entry.source_post_id` — the PLAN's binding, the same
        field `generate.__init__._record` treats as the bound fact — so a bound deck whose trend
        join or vision pass came up empty still files a row saying no badge is being rendered.

        `detected: False` is exactly that operational claim — this deck ships no badge — and not
        the archaeological one that the source certainly had none: a deck with no slide
        intelligence never got to look. `rule` separates the two strong accept rules from the two
        offset ones, which is what an operator staring at a wrong badge needs; `sample` is slide
        1's badge re-based onto OUR length (`_counter` does the same for every slide), never the
        source's own numbers.
        """
        if not str(self.entry.source_post_id or "").strip():
            return None
        spec = self.counter
        if spec is None:
            return {"detected": False, "rule": "", "pattern": "", "sample": ""}
        return {
            "detected": True,
            "rule": spec.rule,
            # The convention structurally, not an example of it: `sample` beside it is the example,
            # and a second example would say nothing the first did not. Padding and separator carry
            # their exact spacing because that spacing IS the source's hand (`01 / 06` vs `1/6`).
            "pattern": (f"pad={spec.pad} sep={spec.separator!r} total_pad={spec.total_pad} "
                        f"prefix={spec.prefix!r} numerator_only={spec.numerator_only}"),
            "sample": spec.format(1, len(self.texts)),
        }

    def _counter(self, number: int) -> str:
        """This slide's badge, re-based onto OUR deck: `"3/5"`, `"03 / 05"`, `"// 03"`, or `""`.

        The total is `len(self.texts)` — the number of slides this deck actually ships — never the
        source's panel count. A five-slide deck cut from a nine-panel source (§0.4′) that printed
        "3/9" would be telling the reader four slides are missing.
        """
        return self.counter.format(number, len(self.texts)) if self.counter is not None else ""

    def _sanctioned_marks(self, number: int) -> list[str]:
        """The real logos this slide may draw — D-A's whole gate, applied once for prompt and check.

        The source list is the vision pass's `brand_marks` for THIS panel: what the panel actually
        showed. Three kinds of entry are removed before anything is sanctioned, and each removal is
        a rule this project already has elsewhere:

        * a configured or LLM-stripped COMPETITOR (M6/§1.5) — the screen's verdict outranks the
          panel's contents, and a competitor logo drawn in full colour is the one outcome the
          blocklist exists to prevent;
        * the source AUTHOR's own identity — a creator's mark is their signature, and reproducing
          it is passing their brand off inside ours (FR-292 signs our decks, not theirs);
        * anything CHROME-shaped — watermarks, @handles, platform marks. The render templates ban
          platform UI in every frame whatever this line says, so sanctioning it would only put the
          two instructions at war.

        What survives is the product mark the panel was about, cleaned to its NAME ("Notion logo
        icon" -> "Notion"): the descriptor is how the vision model named what it saw, and passing
        it through would have the render model drawing the word "logo".
        """
        intel = self._intel()
        slide = intel.slide(number) if intel is not None else None
        # A one-character blocklist entry would match every mark ever named, so the substring test
        # starts at two: over-blocking costs a generic shape, under-blocking costs a competitor's
        # logo drawn in full brand colour on our slide.
        blocked = tuple(word for word in (c.strip().casefold() for c in self._competitors)
                        if len(word) >= 2)
        author = collapse(str(getattr(self.source_post, "author", "") or ""))
        out: list[str] = []
        for raw in list(getattr(slide, "brand_marks", ()) or ())[:_MAX_MARKS_READ]:
            name = mark_name(str(raw or ""))
            folded = name.casefold()
            if not name or _is_chrome(str(raw)) or any(word in folded for word in blocked):
                continue
            if author and author in collapse(name):
                continue
            if folded not in {existing.casefold() for existing in out}:
                out.append(name)
        return out[:_MAX_MARKS]

    @property
    def _competitors(self) -> tuple[str, ...]:
        """M6's strip list for this entry: the config blocklist plus this topic's guarded LLM
        strips. Read through `getattr` like every Env read here (the duck-typed surface), and used
        BOTH as the prompt context's `competitor_strings` and as D-A's sanction filter — one list,
        so a brand cannot be forbidden in the prose and sanctioned as a logo in the same slide."""
        return (*map(str, getattr(getattr(self.env, "branding", None), "competitors", ())),
                *map(str, getattr(self.env, "strip_brands", {}).get(self.entry.trend_key or "",
                                                                    ())))

    def _panel_source_line(self, number: int) -> str:
        """FR-304's position line — `source panel i of N` — only for a panel-mapped deck."""
        post = self.source_post
        if post is None:
            return ""
        width = int(getattr(post, "panel_count", 0) or 0) or len(self.texts)
        return f"source panel {number} of {width}"

    @property
    def _limits(self) -> Any:
        """This deck's render-profile limits — reference ceiling and 50 §7's prompt bound."""
        return render.get_profile(self.env.config.models.image_profile).limits

    def _prompt_cap(self, fix: str) -> int | None:
        """50 §7's prompt ceiling, with the fix suffix's room RESERVED on every pass (F1-C).

        The problem this closes. `PromptEngine.render(suffix=...)` counts the suffix inside
        `max_chars` — correctly, because the provider counts it — so passing the raw profile limit
        gave a first render `cap` characters of body and a re-render `cap - len(fix) - 2`. The
        assembler drops the assembled TAIL first, and this template's tail is the back half of its
        CONSTRAINTS: the @handle/URL ban, the exclusions, the text budgets, the no-duplicate rule.
        Round 2 was therefore judged against rules round 2 was never sent, which is a loop that
        oscillates instead of converging — measured at 924–1,248 characters of lost rulebook per
        fix round in the 2026-08-14 acceptance run, and one of the defects behind its blocked decks.

        The formula. Hold `gauntlet.fix_reserve` back always, then hand the actual suffix's room
        BACK when there is one, and never exceed the provider's own limit::

            (cap - reserve) + (len(fix) + 2 if fix else 0), capped at cap

        First render: `cap - reserve` of body and no suffix. Re-render: the same `cap - reserve` of
        body, with the real fix riding in the space that was reserved for it. Identical body
        budgets, which is the point — the deck's slides must be assembled the same way whichever
        round they were rendered in.

        Args:
            fix: the gauntlet's canned remedy suffix, or `""` on a first pass.

        Returns:
            The `max_chars` to render under, or `None` for a profile that declares no limit (the
            reservation would be arithmetic on an absent number, and a suffix cannot overflow a
            wall that does not exist).
        """
        cap = self._limits.max_prompt_chars
        if not cap:
            return None
        if self.fix_reserve_chars < 0:  # once per deck: the sheet is a file read, not a constant
            self.fix_reserve_chars = gauntlet.fix_reserve(self.env.engine)
        room = int(cap) - self.fix_reserve_chars + (len(fix) + _SUFFIX_SEPARATOR if fix else 0)
        # The floor is paranoia about configuration, not about this run: a profile whose declared
        # limit is smaller than the fix channel itself would otherwise ask the assembler for a
        # negative budget. One character of body is a hard-truncation event the operator sees.
        return max(1, min(int(cap), room))

    @property
    def _limit(self) -> int:
        """The profile's declared reference ceiling — cap before spending, never after (FR-272).

        Post-D46 the only inbound references are a brief's own photos (`refs.attach()`) and the
        chained anchor, which may still occupy a slot in this provider ceiling.
        """
        return self._limits.max_image_urls or 16

    def _input(self, number: int) -> Path | str:
        """A check input at NATIVE resolution — the local file when it landed, else its URL."""
        return self.paths.get(number) or (self.anchor_url if number == 1 else "")

    def _note(self, reason: str, *, error: bool = False, lost: bool = True,
              defect: bool = False) -> bool:
        """Record one setback and log it. Always False, so callers can `return self._note(...)`.

        Two different events wear one shape here, and only one of them is a LOSS. `lost=True` is a
        slide that will not be delivered: it joins `self.reasons`, which becomes the deck's
        `carousel_incomplete` detail and, when nothing lands at all, its `skip_reason`. `lost=False`
        is a vision RE-RENDER that did not happen — declined by the cap, halted, or failed — where
        the slide it was improving is already on disk and ships as first rendered (FR-105/D3). That
        line belongs in the log and NOT in the loss ledger: `missing_slide_numbers` and `detail`
        are read as one sentence, and a re-render's failure in `detail` names a slide that is not
        missing.

        `defect=True` is the third distinction and D51's whole trigger: this loss is a RENDER
        DEFECT that has already used everything the pipeline has for it (FR-317's resubmit, and for
        slide 1 FR-95's replacement anchor), so the slide is never coming and the deck can never be
        whole. It is set only by the paths that know that — a terminal provider failure, a
        deterministic prompt failure, a packaging failure that is not a full disk — and never by
        the ones that describe the RUN stopping rather than the render failing: halt, deadline,
        runway refusal, exhausted credits, full disk. Those keep 10 §10's partial deck.
        """
        if defect and lost and not self.doomed:
            self.doomed = reason
        if not lost:
            self.env.log.warn(
                "vision_retry_unavailable",
                f"{self.entry.asset_id}: {reason} — the flagged slide ships as first rendered "
                "(FR-105)", asset_id=self.entry.asset_id)
            return False
        self.reasons.append(reason)
        (self.env.log.error if error else self.env.log.warn)(
            "carousel_slide_lost", f"{self.entry.asset_id}: {reason}",
            asset_id=self.entry.asset_id)
        return False


__all__ = ["COVERS_DIR", "COVER_CANDIDATE_STEM", "DECK_VIABILITY_LOSS", "GAUNTLET_CRAFT",
           "GAUNTLET_DEGRADED", "GUIDANCE_COVER", "GUIDANCE_SLIDE", "PANELS_TRUNCATED",
           "ROLE_ANCHOR", "ROLE_SLIDE", "ReserveKind", "Submit", "render_carousel"]
