"""CAROUSEL — one deck, anchored: slide 1 first and checked, slides 2–N template-locked.

Module contract
---------------
Purpose: turn ONE approved carousel plan entry into a folder of slide files and one terminal
`meta.yaml`. Owns the FR-95 anchor chain, the FR-105 ordering around it, the per-slide FR-97
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
- **The anchor is checked BEFORE slides 2–N are submitted** (FR-105/95). Slide 1 is a chained
  artifact — every other slide copies it — so a garbled headline found afterwards is found N
  renders too late. Its single re-render is discretionary (FR-106c); a declined or failed retry
  ships the flagged anchor and records `retried_failed`. The deck anchors to the FINAL slide 1.
- **`{{style_dna}}` is built ONCE per deck and is byte-identical in every slide's context**
  (FR-189/M9) — a deck reads as one deck through templating, never through a consistency check
  (FR-20 explicitly has none). Cover-vs-body divergence lives in the assigned style's
  `per_format_guidance` instead: slide 1 renders under its `carousel_cover` prose and slides 2–N
  under `carousel_slide`, appended to `{{render_prompt}}` — the one block a deck is ALLOWED to
  vary, because the anchor is a cover and the rest are pages.
- **The anchor-failure fallback is PRE-COMMITTED work** (FR-95/FR-106b, plan §2 T4.3): all N
  slides re-render independently and none may be declined by the cap. Cap bookkeeping must never
  be the thing that splits a deck.
- **A partial deck ships** (FR-20, 10 §10): delivered slides stay, `missing_slide_numbers` names
  the rest 1-indexed, the asset is tagged `incomplete`. Zero slides delivered is a failed
  creative that KEEPS its paid caption (FR-74).
- **Nothing raises.** `render.KieOutOfCredits` latches `env.credits_exhausted` and the deck is
  packaged as it stands (FR-167); `env.halted` is re-read before EVERY submission, so Ctrl+C and
  the deadline stop ordering mid-deck rather than mid-run (FR-201/108).

- **One re-render and one re-check per flagged slide, then it ships** (FR-105/NFR-4). A delivered
  re-render IS re-checked — the estimator prices the vision-retry allowance as render plus
  re-check, and `retried_passed` is only honest when a real second verdict says so. Re-checks are
  batched into one call for every slide re-rendered in the same pass. A re-render that never
  happens loses NOTHING: the slide it was improving is already on disk, so its failure is logged
  as `vision_retry_unavailable` and never joins the deck's missing-slide ledger.
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
- **Every checked slide travels with the words it was ordered to carry** (FR-105, v2.1.1), and on
  a panel-mapped deck the retry may not touch them (FR-304 carve-out): the check's third question
  is "do the rendered words match the source panel?", and the answer to it is the reason
  `vision_check` is on by default — the 2026-08-13 audit shipped a slide of invented copy that
  both older questions passed.

Do not: call `render.run`, reserve or reconcile money, compute a price, write a ledger line, name
a Kie field, check anything twice beyond that single re-check, or import `hypesocials.generate`
at runtime — that package imports this module.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from hypesocials import render, vision_check
from hypesocials.models import (
    AssetRecord, CopySet, DegradationTag, MetaStyle, PlanEntry, PlanEntryStatus, RenderFailCause,
    RenderOutcome, RenderOutcomeKind, RenderParams, RenderPriority, RenderRefs, SourcePost,
    VisionCheckResult,
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
from hypesocials.generate.refs import (
    Reference, attach, branding_block, role_lines, style_of, upload_local, wordmark,
)
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

ReserveKind = Literal["projected", "precommitted", "discretionary"]  # FR-106 a/b/c

_CREDITS = "kie_credits_exhausted — top up your Kie.ai credits (FR-167)"
#: Worst first: one `retried_failed` slide makes the whole deck `retried_failed` (FR-27 honesty).
_SEVERITY = (VisionCheckResult.RETRIED_FAILED, VisionCheckResult.RETRIED_PASSED,
             VisionCheckResult.PASSED)
_FALLBACK_SLIDES = 5
#: FR-73's `panels_truncated` (§0.4′): the source deck was longer than the platform ceiling, so it
#: ships as its first N panels with the indices preserved. Resolved off `DegradationTag` when that
#: enum carries the member and spelled literally until then — `models.py` belongs to another task
#: this wave, `AssetFolder.mark` stores whatever it is given, and `DegradationTag` is a `str` enum,
#: so the bytes in `meta.yaml` are identical either way.
PANELS_TRUNCATED = getattr(DegradationTag, "PANELS_TRUNCATED", "panels_truncated")

#: D-A: how many of a panel's named marks are even considered, and how many may be sanctioned onto
#: one slide. A panel showing nine real logos is an icon grid, and telling the render model to draw
#: nine real marks faithfully is how it draws nine invented ones.
_MAX_MARKS_READ = 10
_MAX_MARKS = 4
#: The descriptors the vision pass appends when it names what it saw ("Notion logo icon"). They
#: describe the ENTRY, not the brand, and a render model given them draws the word.
_MARK_DESCRIPTORS = ("logo", "logos", "icon", "icons", "wordmark", "mark", "marks", "badge",
                     "glyph", "symbol", "app", "lockup",
                     # shape words a vision pass uses for a glyph it recognizes ("Claude
                     # asterisk icon", 59el deck 06) — descriptors of the mark, never the brand
                     "asterisk", "sunburst", "emblem")
#: The characters a vision pass uses to staple two descriptors onto one word ("logo/wordmark",
#: "logo+wordmark", "logo & wordmark"). Split as separators AND kept, so `_mark_name` can peel the
#: pieces and then rebuild whatever survived exactly as it was written.
_JOINER = re.compile(r"([/+&])")
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


def _mark_name(raw: str) -> str:
    """`"Notion logo icon"` -> `"Notion"` — the brand, without the words that described the entry.

    Trailing descriptors are peeled one at a time, so "app icon" and "logo mark" both reduce; a
    string that is ONLY descriptors ("logo") reduces to nothing and is therefore never sanctioned,
    which is the right answer for a mark whose brand the vision pass could not name.

    JOINED descriptors peel too (v2.1.4). A vision pass writes "Claude logo/wordmark" as readily
    as "Claude logo", and to a peeler that splits on whitespace `logo/wordmark` is one unknown
    word: the peel stopped dead, the name stayed `"Claude logo/wordmark"`, and `_patch_refs`' join
    onto the patch table (keyed `claude`) missed. In the glz0 run that cost deck 06 the Claude
    patch it had already cropped and uploaded — `mark_patches_attached patched: []` — and the
    cover recoloured the Claude mark into the style's teal, which is the exact defect FR-315 was
    built to end. So `/`, `+` and `&` are treated as word breaks WHILE peeling.

    They are not, however, rewritten. Each word is exploded on its joiners, the descriptor tail is
    peeled off the pieces, and whatever survives is rebuilt with its ORIGINAL joiner — so
    "AT&T logo" reduces to "AT&T" and never to "AT T". A brand whose name contains an ampersand
    is a brand, not a list.
    """
    # A trailing comma-clause is a LOCATION, not a name: the vision pass writes "Claude
    # logo/wordmark, top left" and "Claude asterisk icon, inside Decision Brief banner". The
    # 59el run proved the peeler cannot exhaust free-form location prose ("top", "left",
    # "banner"…), so everything after the first comma is cut before peeling begins — a brand
    # name containing a comma is not a thing the registry or the vision pass produces.
    raw = str(raw or "").split(",", 1)[0]
    pieces: list[tuple[str, str]] = []  # (joiner that PRECEDES this piece, piece)
    for index, word in enumerate(raw.replace("(", " ").replace(")", " ").split()):
        parts = _JOINER.split(word)  # ['logo', '/', 'wordmark'] — separators kept
        pieces.append((" " if index else "", parts[0]))
        pieces.extend(zip(parts[1::2], parts[2::2]))
    while pieces and (not (tail := pieces[-1][1].strip(".,:;'\""))
                      or tail.casefold() in _MARK_DESCRIPTORS):
        pieces.pop()  # an empty piece is a dangling joiner ("Claude logo / wordmark"), not a name
    return "".join(joiner + piece for joiner, piece in pieces).strip(" -–—,:;\"'/+&")


def _is_chrome(raw: str) -> bool:
    """True for a mark that is the creator's or the platform's furniture, not a product logo."""
    folded = str(raw or "").casefold()
    return "@" in folded or any(word in folded for word in _CHROME_WORDS)


def _collapse(text: str) -> str:
    """`"@The Roman Knox"` -> `"theromanknox"` — one identity, however it was typed.

    A creator's mark is transcribed as an @handle on one slide and as a spaced account name on the
    next, so the author test has to compare the two with the punctuation and spacing gone.
    """
    return "".join(char for char in str(text or "").casefold() if char.isalnum())


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
    #: Slide -> the text actually ORDERED for it, when a retry changed it (FR-105). Only a
    #: free-composed line can differ from `texts`; a mapped panel is byte-identical by contract.
    ordered: dict[int, str] = field(default_factory=dict)
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
    outcomes: list[RenderOutcome] = field(default_factory=list)  # EVERY submission, failures too
    paths: dict[int, Path] = field(default_factory=dict)
    delivered: set[int] = field(default_factory=set)
    retried: set[int] = field(default_factory=set)  # one vision retry per slide (NFR-4)
    #: FR-317's SEPARATE one-shot ledger: slides whose job has already been resubmitted once. Kept
    #: apart from `retried` on purpose — that set is the vision retry's, and a slide is entitled to
    #: one of each (a job that timed out, was resubmitted, landed, and was then flagged).
    resubmitted: set[int] = field(default_factory=set)
    checks: list[VisionCheckResult] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    abandoned: bool = False
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
        """Anchor, check, deck — or the independent-slide fallback when the anchor never lands."""
        self._mark_truncation()
        self.attached = await attach(self.entry, self.env, self.folder)
        await self._crop_patches()  # FR-315: once per deck, before the first slide is priced
        self.anchored = bool(self.env.config.run.carousel_anchor)
        if self.anchored:
            await self._slide(1, anchor=False, kind="projected", priority=RenderPriority.WAVE1)
            if self.anchor_url:
                await self._check([1], RenderPriority.WAVE1)  # FR-105: BEFORE slides 2–N exist
                await self._burst(range(2, len(self.texts) + 1))
                await self._check(sorted(self.delivered), RenderPriority.WAVE2)
                return
            self.anchored = False
            self.env.log.warn(
                "carousel_anchor_fallback",
                f"{self.entry.asset_id}: slide 1 never landed; the deck falls back to independent "
                "generation of all slides from the style references (FR-95)",
                asset_id=self.entry.asset_id, slides=len(self.texts))
        # The FR-95 fallback and the `carousel_anchor: false` A/B control are the same shape, and
        # both are PRE-COMMITTED wave-2 work — never discretionary (FR-106b, plan §2 T4.3).
        await self._burst(range(1, len(self.texts) + 1))
        await self._check(sorted(self.delivered), RenderPriority.WAVE2)

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

        The crop is SYNCHRONOUS (file read + decode + PNG write) and runs on a worker thread: it is
        real work, and the event loop here is also carrying every other creative in the run.
        """
        intel = self._intel()
        boxes = list(getattr(intel, "mark_boxes", ()) or ()) if intel is not None else []
        folder = str(getattr(intel, "folder", "") or "")
        run_dir = getattr(self.env, "run_dir", "")
        if not boxes or not folder or not run_dir:
            return
        try:
            cropped = await asyncio.to_thread(crop_marks, Path(run_dir) / folder, boxes)
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
                self.patches[_collapse(_mark_name(name))] = url
        self.env.log.event(
            "mark_patches_ready",
            f"{self.entry.asset_id}: {len(self.patches)} of {len(cropped)} cropped mark patch(es) "
            f"uploaded from {len(boxes)} detected box(es)", asset_id=self.entry.asset_id,
            boxes=len(boxes), cropped=len(cropped), uploaded=len(self.patches),
            marks=sorted(cropped))

    async def _burst(self, numbers: range) -> None:
        """Every remaining slide at once — inside a wave nothing waits for a sibling (FR-25)."""
        await asyncio.gather(*(
            self._slide(number, anchor=self.anchored, kind="precommitted",
                        priority=RenderPriority.WAVE2) for number in numbers))

    async def _slide(
        self, number: int, *, anchor: bool, kind: ReserveKind, priority: RenderPriority,
        plan: vision_check.RetryPlan | None = None,
    ) -> bool:
        """Render one slide and put its bytes on disk. True when that slide was delivered."""
        env = self.env
        # A vision RE-RENDER (`plan is not None`) can fail without losing anything: the slide it
        # was improving is already on disk and already shipping. Its failures are therefore logged
        # but kept out of `self.reasons`, which is the deck's ledger of slides that are MISSING —
        # a "slide 3: declined by the spend cap" line beside `missing_slide_numbers: [5]` told the
        # operator slide 3 was lost when slide 3 was delivered (FR-73/FR-105).
        lost = plan is None
        if env.halted:  # re-read before EVERY submission (FR-201/108)
            self.abandoned = self.abandoned or not self.outcomes
            return self._note(f"slide {number}: interrupted before submission", lost=lost)
        if env.credits_exhausted:
            return self._note(f"slide {number}: {_CREDITS}", lost=lost)
        refs = self._refs(number, anchor)
        prompt = self._prompt(number, anchor=anchor, refs=refs, plan=plan)
        if prompt is None:
            return self._note(f"slide {number}: prompt_assembly_failed — unresolved placeholder "
                              "(FR-260)", error=True, lost=lost)
        urls = [ref.url for ref in refs]
        # FR-241 decides the route by exactly this test inside `render/profiles.py`, so recording
        # it here is an observation of the same fact rather than a second opinion about it.
        self.edit_route = self.edit_route or bool(urls)
        self.text_route = self.text_route or not urls
        outcome = await self._call(number, prompt, urls, kind=kind,
                                   priority=priority, lost=lost)
        if outcome is None:
            return False
        url = outcome.result_urls[0] if outcome.result_urls else ""
        if outcome.kind is not RenderOutcomeKind.SUCCESS or not url:
            # FR-242: a `success` with nothing behind it is a failure that lies.
            cause = outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value
            return self._note(f"slide {number}: {cause} — "
                              f"{outcome.fail_message or 'no usable result'}", error=True,
                              lost=lost)
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
            return self._note(f"slide {number}: {exc.reason}", error=True, lost=lost)
        self.delivered.add(number)
        return True

    async def _call(
        self, number: int, prompt: str, urls: list[str], *, kind: ReserveKind,
        priority: RenderPriority, lost: bool = True,
    ) -> RenderOutcome | None:
        """The one door to `submit`: tally every outcome, apply FR-97 and FR-317, swallow the 402.

        Two single retries live here and they answer different questions. FR-97's is about the
        REQUEST — a content-policy refusal is re-asked without its references, because that is
        what a moderation refusal is usually about. FR-317's is about the JOB — a timeout or an
        ordinary provider failure is the same request again, unchanged, because nothing about it
        was wrong (D48). They never stack on one attempt: a moderation refusal is excluded from
        FR-317 by name, and whichever attempt is standing when the retries are done is returned.
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
        return await self._resubmit(number, prompt, urls, outcome, priority=priority, lost=lost)

    async def _resubmit(
        self, number: int, prompt: str, urls: list[str], outcome: RenderOutcome | None, *,
        priority: RenderPriority, lost: bool,
    ) -> RenderOutcome | None:
        """FR-317's ONE automatic resubmit of a timed-out or non-moderation-failed slide job.

        Returns the outcome the caller should treat as this attempt's result: the resubmission when
        one happened and produced anything at all, otherwise the failure it was given. A second
        failure is FINAL — the slide flows into the ordinary lost-slide path with the second job's
        own cause, and `self.resubmitted` guarantees there is never a third.

        Deliberately NOT applied to:
        * a moderation refusal — FR-97 owns that failure and answering it with the identical
          request would buy the identical refusal;
        * a declined submission (`None`) — nothing was ordered, so there is nothing to re-order;
        * a halted or credit-exhausted run — `env.halted` is re-read HERE, immediately before the
          resubmission, because the first attempt may have spent the whole timeout inside the
          window where Ctrl+C landed (FR-201/108/167).

        The money is `discretionary` (FR-106c): a resubmit is real, optional spend the cap may
        decline, and the timed-out attempt it replaces already reconciled at $0 (`_billed_usd`),
        so a deck that resubmits is billed for the renders it got, not for the ones that never
        came back.
        """
        env = self.env
        if (outcome is None or outcome.kind is RenderOutcomeKind.SUCCESS
                or outcome.fail_cause is RenderFailCause.MODERATION
                or number in self.resubmitted):
            return outcome
        cause = outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value
        if env.halted or env.credits_exhausted:
            env.log.warn(
                "image_job_resubmit_skipped",
                f"{self.entry.asset_id} slide {number}: {cause} — the run stopped ordering work, "
                "so FR-317's one resubmit is not taken and the slide is lost",
                asset_id=self.entry.asset_id, slide=number, cause=cause)
            return outcome
        self.resubmitted.add(number)  # one-shot, before the await: no path may take it twice
        env.log.warn(
            "image_job_resubmit",
            f"{self.entry.asset_id} slide {number}: {cause} "
            f"({outcome.fail_message or 'no usable result'}) — resubmitting the SAME job once "
            "(FR-317, attempt 2 of 2); a second failure is final",
            asset_id=self.entry.asset_id, slide=number, cause=cause, attempt=2,
            task_id=outcome.task_id, detail=outcome.fail_message)
        again = await self._submit(prompt, urls, kind="discretionary", priority=priority,
                                   lost=lost, label=f"resubmit · slide {number}")
        return again if again is not None else outcome

    async def _submit(
        self, prompt: str, urls: list[str], *, kind: ReserveKind, priority: RenderPriority,
        label: str, lost: bool = True,
    ) -> RenderOutcome | None:
        try:
            outcome = await self.submit(
                self.entry, RenderParams(prompt=prompt, aspect_ratio=self.entry.aspect_ratio),
                RenderRefs(image_urls=list(urls)), job="slide", priority=priority, kind=kind,
                label=label)
        except render.KieOutOfCredits as exc:
            self.env.credits_exhausted = True  # FR-167: latched once, for the whole run
            self._note(f"{label}: {_CREDITS} ({exc})", lost=lost)
            return None
        if outcome is None:
            self._note(f"{label}: declined by the spend cap (FR-106c)", lost=lost)
            return None
        self.outcomes.append(outcome)
        return outcome

    # -------------------------------------------------------------------- vision check (FR-105)

    async def _check(self, numbers: list[int], priority: RenderPriority) -> None:
        """Check these slides, re-render whatever is flagged, then re-check what was re-rendered.

        Three call shapes, all batched (FR-105/107): one call for the whole set, at most one
        discretionary re-render per flagged slide (FR-106c), and ONE further call carrying every
        slide whose re-render landed. A slide already re-rendered in an earlier pass keeps its
        one retry (NFR-4) and stays `retried_failed` if it is still flagged.
        """
        if not self._checking or not numbers:
            return
        first = await self._verdicts(numbers)
        flagged = [n for n in numbers
                   if n not in self.retried and (v := first.get(n)) is not None and v.flagged]
        self.retried.update(flagged)
        landed = [number for number, delivered in zip(flagged, await asyncio.gather(
            *(self._rerender(number, first[number], priority) for number in flagged)))
            if delivered]
        # A declined or failed re-render never earns a second look — `verdict_result` then reads
        # a flagged first verdict with no second one and says so (FR-27's `retried_failed`).
        after = await self._verdicts(landed)
        self._log_rechecks(landed, after)
        self.checks.extend(
            vision_check.verdict_result(first.get(n), after.get(n), retried=n in flagged)
            for n in numbers)

    def _log_rechecks(
        self, numbers: list[int], after: dict[int, vision_check.ImageVerdict | None]
    ) -> None:
        """FR-321d: the SECOND verdict, on the record, per re-rendered slide.

        `vision_check_result` claims one of four states and `retried_passed` is the only one that
        asserts a defect was fixed. Until now that assertion rested on a verdict nothing logged, so
        the operator could read the claim and not the evidence. This is the evidence: one
        `vision_recheck` line per slide that was actually re-rendered and re-checked, carrying the
        same three defect flags the first pass logged under `vision_check_flagged`. It is a record,
        not a decision — the verdict it prints is already the one `verdict_result` is about to use,
        and there is never a third render whatever it says.
        """
        for number in numbers:
            verdict = after.get(number)
            state = "clean" if verdict is not None and not verdict.flagged else (
                "still flagged" if verdict is not None else "no verdict returned")
            self.env.log.event(
                "vision_recheck",
                f"{self.entry.asset_id} slide {number} re-checked after its one re-render: "
                f"{state}", asset_id=self.entry.asset_id, slide=number, attempt=2,
                checked=verdict is not None,
                flagged=bool(verdict is not None and verdict.flagged),
                text_broken=bool(verdict is not None and verdict.text_broken),
                fake_ui=bool(verdict is not None and verdict.fake_ui),
                text_mismatch=bool(verdict is not None and verdict.text_mismatch),
                detail=(verdict.detail if verdict is not None else ""))

    async def _verdicts(
        self, numbers: list[int]
    ) -> dict[int, vision_check.ImageVerdict | None]:
        """ONE multi-image call for these slides — N slides never cost N calls (FR-105/107).

        Each slide travels beside the words it was ORDERED to carry (FR-105 v2.1.1). Without that
        referent the third question — does the render say what the source panel said? — cannot be
        asked at all, and a slide that renders clean-but-wrong copy passes: the 2026-08-13 audit
        shipped exactly that. A wordless mapped panel sends an EMPTY string, which is the stronger
        statement of the two: nothing may appear there.

        The slide's SANCTIONED marks travel with it too (D-A, v2.1.2), and for the mirror reason:
        the check's fake-UI question is asked about a slide we deliberately ordered a real Notion
        logo on, and the mismatch question about lettering that is part of that logo rather than
        typeset copy. Ordering a mark and then flagging it would spend the retry undoing the
        fidelity that ordered it.
        """
        if not numbers:
            return {}
        report = await vision_check.check(
            [self._input(n) for n in numbers],
            expected=[self._expected(n) for n in numbers],
            sanctioned_marks=[self._sanctioned_marks(n) for n in numbers],
            call=self.env.llm_call, engine=self.env.engine, log=self.env.log)
        return {number: report.verdict_for(position)
                for position, number in enumerate(numbers, start=1)}

    async def _rerender(
        self, number: int, verdict: vision_check.ImageVerdict, priority: RenderPriority,
    ) -> bool:
        """FR-105's single discretionary re-render of one flagged slide, in place."""
        self.env.log.warn("vision_check_flagged",
                          f"{self.entry.asset_id} slide {number} flagged: {verdict.detail}",
                          asset_id=self.entry.asset_id, slide=number,
                          text_broken=verdict.text_broken, fake_ui=verdict.fake_ui,
                          text_mismatch=verdict.text_mismatch)
        # D-F: the verdict travels into the plan, so the re-render is told WHICH defect was seen.
        # "Shorter text, larger type" is the remedy for a garbled glyph and a no-op for a render
        # that invented words or drew a fake interface — the two failures that earned this retry
        # most often in the 2026-08-13 audit.
        plan = self._retry_plan(number, verdict)
        # What the RE-CHECK must compare against is what the re-render was ordered to carry, which
        # is the plan's text — identical to the panel under the FR-304 carve-out, shorter when the
        # deck composed its own words. Recording it here keeps the second verdict honest instead
        # of flagging a legitimately shortened line as a mismatch with the original.
        self.ordered[number] = plan.slide_text
        return await self._slide(number, anchor=self.anchored and number != 1,
                                 kind="discretionary", priority=priority, plan=plan)

    # --------------------------------------------------------------------------------- inputs

    def _refs(self, number: int, anchor: bool) -> list[Reference]:
        """Slide 1 leads for slides 2–N (FR-95 PRIMARY), then the brief's photos, then FR-315's
        mark patches, then the hard cap.

        Order is the contract: the anchor is `Image 1` and outranks everything (FR-190 rewrites its
        role line from `carousel_anchor_instruction.md` over position 0), and the patches come last
        because they are the narrowest attachments in the set — one logo each, contributing nothing
        but their own pixels. The cap is the provider's, applied once at the end, so a deck with a
        photo-heavy brief loses patches rather than losing its anchor.
        """
        refs = ([Reference(self.anchor_url, _ANCHOR_ROLE), *self.attached]  # role -> ROLE_ANCHOR
                if anchor and self.anchor_url else list(self.attached))
        refs.extend(self._patch_refs(number))
        return refs[:self._limit]

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
        # table is keyed `_collapse(_mark_name(box_name))` at upload; matching a sanctioned name
        # with `_collapse` alone made the join depend on the two strings having been *written* the
        # same way, and in glz0 they were not — box `"Claude"`, sanctioned `"Claude logo/wordmark"`,
        # no match, no patch, a recoloured logo. `_mark_name` is idempotent, so applying it to an
        # already-cleaned name is free and the symmetry is now structural rather than incidental.
        keys = {name: _collapse(_mark_name(name)) for name in sanctioned}
        refs = [Reference(self.patches[keys[name]], _MARK_PATCH_ROLE.format(name=name))
                for name in sanctioned if keys[name] in self.patches]
        self.env.log.event(
            "mark_patches_attached",
            f"{self.entry.asset_id} slide {number}: {len(refs)} of {len(sanctioned)} sanctioned "
            f"mark(s) ride as cropped patches", verbose_only=True, asset_id=self.entry.asset_id,
            slide=number, patched=[name for name in sanctioned if keys[name] in self.patches],
            name_only=[name for name in sanctioned if keys[name] not in self.patches])
        return refs[:_MAX_MARK_PATCHES]

    def _prompt(
        self, number: int, *, anchor: bool, refs: list[Reference],
        plan: vision_check.RetryPlan | None,
    ) -> str | None:
        """One slide's finished prompt, or `None` when it cannot be filled (FR-260)."""
        env = self.env
        copyset = plan.copy if plan is not None else self.copy
        text = plan.slide_text if plan is not None else self.texts[number - 1]
        if copyset is not None and not text.strip():
            # FR-304: a wordless source panel renders wordless. `prompts_engine._onimage_text`
            # falls back to `copy.headline` when a carousel slide's text is empty (`slide_text or
            # headline`) — the last repeat path left in the deck — so this slide's context gets a
            # headline-free copy of the CopySet. A local blanking, not a mutation: the deck's own
            # copy is what the caption, the retry plan and every other slide still read.
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
                budget_scale=plan.budget_scale if plan is not None else 1.0,
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
                max_chars=self._limits.max_prompt_chars,  # 50 §7
                # FR-193: the retry repeats the preserve list and adds one line. It goes through
                # the engine rather than being appended after it, because the provider measures
                # the whole string: three glz0 retry prompts were built by appending this block to
                # a prompt already at the limit, so nothing guarded them and each bought an HTTP
                # 500 that FR-317 then bought twice.
                suffix=plan.instruction if plan is not None else "")
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
                      references=len(urls), retry=plan is not None, prompt=prompt)
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

    def _retry_plan(
        self, number: int, verdict: vision_check.ImageVerdict | None = None
    ) -> vision_check.RetryPlan:
        """FR-105's retry: a different request, not a plea — and never a trimmed quote.

        On a panel-mapped deck (`source_post is not None`, the same test `_panel_note` and
        `_panel_source_line` make) this slide's line IS source panel *i*, verbatim under FR-304,
        so it passes through untouched and the retry varies the layout instead (v2.1.1). The
        −40% cut survives only for a deck that composed its own words — measured against the
        `slide` budget that governs a deck slide, never against `image_headline`, which is where
        a 131-character panel came back as a 53-character mid-sentence stub.

        `verdict` (D-F) is the first pass's answer for THIS slide; it changes the instruction only
        — an invented word is forbidden by name, a fake interface is forbidden by name — and never
        the text, which stays governed by the verbatim rule above.
        """
        return vision_check.retry_plan(
            self.copy or CopySet(asset_id=self.entry.asset_id, language=self.entry.language),
            "carousel", self.env.config.run.text_budgets, slide_text=self.texts[number - 1],
            verbatim=self.source_post is not None, verdict=verdict)

    def _expected(self, number: int) -> str:
        """The words this slide was ordered to carry — the check's referent (FR-105 v2.1.1).

        `ordered` wins over `texts` for a slide already re-rendered under a retry plan, and slide 1
        carries the deck's wordmark because that is the one signed slide (M12) and the signature
        renders through the TEXT block (B1) — an unlisted wordmark would read as an invented word.
        The counter is listed for the same reason and on every slide (D-D): the badge was ORDERED
        as a locked string, so an unlisted "3/5" is three invented characters per slide.
        """
        return vision_check.expected_text(
            self.copy, "carousel",
            slide_text=self.ordered.get(number, self.texts[number - 1]),
            wordmark=self.wordmark if number == 1 else "",
            slide_counter=self._counter(number))

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
            "vision_check_result": self._verdict(),
        }
        if not self.delivered:
            reason = "; ".join(self.reasons[:3]) or "carousel produced no slides"
            entry.status = PlanEntryStatus.ABANDONED if self.abandoned else PlanEntryStatus.FAILED
            entry.skip_reason = entry.skip_reason or reason
            return self.folder.skip(
                reason, DegradationTag.ABANDONED if self.abandoned else None, **fields)
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
            cost_usd=fields["actual_cost_usd"], vision_check=fields["vision_check_result"].value)
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
        ident = _collapse(getattr(self.source_post, "author", "") or "")
        if len(ident) < _MIN_AUTHOR_IDENT:
            return brief
        kept = [part.strip() for part in _SENTENCE_SPLIT.split(brief)
                if part.strip() and ident not in _collapse(part)]
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
        author = _collapse(str(getattr(self.source_post, "author", "") or ""))
        out: list[str] = []
        for raw in list(getattr(slide, "brand_marks", ()) or ())[:_MAX_MARKS_READ]:
            name = _mark_name(str(raw or ""))
            folded = name.casefold()
            if not name or _is_chrome(str(raw)) or any(word in folded for word in blocked):
                continue
            if author and author in _collapse(name):
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
    def _checking(self) -> bool:
        """FR-27: the check runs only when it is on AND a metered LLM call exists to make it."""
        return bool(self.env.config.run.vision_check) and self.env.llm_call is not None

    @property
    def _limits(self) -> Any:
        """This deck's render-profile limits — reference ceiling and 50 §7's prompt bound."""
        return render.get_profile(self.env.config.models.image_profile).limits

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

    def _verdict(self) -> VisionCheckResult:
        """One deck-level state out of every verdict it collected, worst first (FR-27)."""
        return next((state for state in _SEVERITY if state in self.checks),
                    VisionCheckResult.NOT_CHECKED)

    def _note(self, reason: str, *, error: bool = False, lost: bool = True) -> bool:
        """Record one setback and log it. Always False, so callers can `return self._note(...)`.

        Two different events wear one shape here, and only one of them is a LOSS. `lost=True` is a
        slide that will not be delivered: it joins `self.reasons`, which becomes the deck's
        `carousel_incomplete` detail and, when nothing lands at all, its `skip_reason`. `lost=False`
        is a vision RE-RENDER that did not happen — declined by the cap, halted, or failed — where
        the slide it was improving is already on disk and ships as first rendered (FR-105/D3). That
        line belongs in the log and NOT in the loss ledger: `missing_slide_numbers` and `detail`
        are read as one sentence, and a re-render's failure in `detail` names a slide that is not
        missing.
        """
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


__all__ = ["GUIDANCE_COVER", "GUIDANCE_SLIDE", "PANELS_TRUNCATED", "ROLE_ANCHOR", "ROLE_SLIDE",
           "ReserveKind", "Submit", "render_carousel"]
