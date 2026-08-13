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
  batched into one call for every slide re-rendered in the same pass.

Do not: call `render.run`, reserve or reconcile money, compute a price, write a ledger line, name
a Kie field, check anything twice beyond that single re-check, or import `hypesocials.generate`
at runtime — that package imports this module.
"""

from __future__ import annotations

import asyncio
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
from hypesocials.generate.refs import (
    Reference, attach, branding_block, role_lines, style_of, wordmark,
)
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
    attached: list[Reference] = field(default_factory=list)  # style + brief, role-labelled
    anchored: bool = False
    anchor_url: str = ""
    outcomes: list[RenderOutcome] = field(default_factory=list)  # EVERY submission, failures too
    paths: dict[int, Path] = field(default_factory=dict)
    delivered: set[int] = field(default_factory=set)
    retried: set[int] = field(default_factory=set)  # one vision retry per slide (NFR-4)
    checks: list[VisionCheckResult] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    abandoned: bool = False

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

    # ------------------------------------------------------------------------------- ordering

    async def build(self) -> None:
        """Anchor, check, deck — or the independent-slide fallback when the anchor never lands."""
        self._mark_truncation()
        self.attached = await attach(self.entry, self.env, self.folder)
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
        if env.halted:  # re-read before EVERY submission (FR-201/108)
            self.abandoned = self.abandoned or not self.outcomes
            return self._note(f"slide {number}: interrupted before submission")
        if env.credits_exhausted:
            return self._note(f"slide {number}: {_CREDITS}")
        refs = self._refs(anchor)
        prompt = self._prompt(number, anchor=anchor, refs=refs, plan=plan)
        if prompt is None:
            return self._note(f"slide {number}: prompt_assembly_failed — unresolved placeholder "
                              "(FR-260)", error=True)
        outcome = await self._call(number, prompt, [ref.url for ref in refs], kind=kind,
                                   priority=priority)
        if outcome is None:
            return False
        url = outcome.result_urls[0] if outcome.result_urls else ""
        if outcome.kind is not RenderOutcomeKind.SUCCESS or not url:
            # FR-242: a `success` with nothing behind it is a failure that lies.
            cause = outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value
            return self._note(f"slide {number}: {cause} — "
                              f"{outcome.fail_message or 'no usable result'}", error=True)
        if number == 1:
            self.anchor_url = url  # the deck anchors to the FINAL slide 1 (10 §5)
        if env.disk_full:  # 10 §10: further downloads STOP rather than thrash a full disk
            return self._note(f"slide {number}: disk_full — downloads stopped for this run")
        try:  # the bytes stop being a borrowed 24 h URL and become the operator's file
            self.paths[number] = await self.folder.store_render(url, slide=number)
        except PackagingError as exc:  # one lost slide, never a lost deck
            if exc.reason == "disk_full":  # the one failure that outlives this creative
                env.disk_full = True
            return self._note(f"slide {number}: {exc.reason}", error=True)
        self.delivered.add(number)
        return True

    async def _call(
        self, number: int, prompt: str, urls: list[str], *, kind: ReserveKind,
        priority: RenderPriority,
    ) -> RenderOutcome | None:
        """The one door to `submit`: tally every outcome, apply FR-97, swallow the 402 (FR-167)."""
        outcome = await self._submit(prompt, urls, kind=kind, priority=priority,
                                     label=f"carousel slide {number}/{len(self.texts)}"
                                           f"{self._panel_note(number)}"
                                           f" · {self.entry.asset_id}")
        if (outcome is None or outcome.kind is RenderOutcomeKind.SUCCESS
                or outcome.fail_cause is not RenderFailCause.MODERATION or not urls):
            return outcome
        self.env.log.warn("moderation_retry",
                          f"{self.entry.asset_id} slide {number}: content-policy refusal; one "
                          "reference-free retry (FR-97)", asset_id=self.entry.asset_id,
                          slide=number, detail=outcome.fail_message)
        retry = await self._submit(prompt, [], kind="discretionary", priority=priority,
                                   label=f"moderation retry · slide {number}")
        if retry is None:
            return outcome
        self.folder.mark(DegradationTag.REFS_DROPPED_MODERATION)
        return retry

    async def _submit(
        self, prompt: str, urls: list[str], *, kind: ReserveKind, priority: RenderPriority,
        label: str,
    ) -> RenderOutcome | None:
        try:
            outcome = await self.submit(
                self.entry, RenderParams(prompt=prompt, aspect_ratio=self.entry.aspect_ratio),
                RenderRefs(image_urls=list(urls)), job="slide", priority=priority, kind=kind,
                label=label)
        except render.KieOutOfCredits as exc:
            self.env.credits_exhausted = True  # FR-167: latched once, for the whole run
            self._note(f"{label}: {_CREDITS} ({exc})")
            return None
        if outcome is None:
            self._note(f"{label}: declined by the spend cap (FR-106c)")
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
        self.checks.extend(
            vision_check.verdict_result(first.get(n), after.get(n), retried=n in flagged)
            for n in numbers)

    async def _verdicts(
        self, numbers: list[int]
    ) -> dict[int, vision_check.ImageVerdict | None]:
        """ONE multi-image call for these slides — N slides never cost N calls (FR-105/107)."""
        if not numbers:
            return {}
        report = await vision_check.check([self._input(n) for n in numbers],
                                          call=self.env.llm_call, engine=self.env.engine,
                                          log=self.env.log)
        return {number: report.verdict_for(position)
                for position, number in enumerate(numbers, start=1)}

    async def _rerender(
        self, number: int, verdict: vision_check.ImageVerdict, priority: RenderPriority,
    ) -> bool:
        """FR-105's single discretionary re-render of one flagged slide, in place."""
        self.env.log.warn("vision_check_flagged",
                          f"{self.entry.asset_id} slide {number} flagged: {verdict.detail}",
                          asset_id=self.entry.asset_id, slide=number)
        return await self._slide(number, anchor=self.anchored and number != 1,
                                 kind="discretionary", priority=priority,
                                 plan=self._retry_plan(number))

    # --------------------------------------------------------------------------------- inputs

    def _refs(self, anchor: bool) -> list[Reference]:
        """Slide 1 leads for slides 2–N (FR-95 PRIMARY), then the style set, then the hard cap."""
        refs = ([Reference(self.anchor_url, _ANCHOR_ROLE), *self.attached]  # role -> ROLE_ANCHOR
                if anchor and self.anchor_url else list(self.attached))
        return refs[:self._limit]

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
                competitor_strings=(
                    *map(str, getattr(getattr(env, "branding", None), "competitors", ())),
                    *map(str, getattr(env, "strip_brands", {}).get(
                        self.entry.trend_key or "", ()))),
                # M12: an anchored slide 2–N inherits the signature from the picture it reproduces,
                # so the branding block rides the anchor alone; an independently generated deck
                # (`carousel_anchor: false`, or the FR-95 fallback) needs it on every slide.
                branding_block=self.branding if number == 1 or not anchor else "",
                # M12, the strict half: the WORDMARK is slide 1's alone, whatever the deck's
                # shape. A deck signed once reads as designed; signed N times it reads as a
                # watermark, and `carousel_anchor_instruction.md` tells slides 2–N never to refill
                # the signature zone.
                wordmark=self.wordmark if number == 1 else "",
                text_budgets=env.config.run.text_budgets,
                budget_scale=plan.budget_scale if plan is not None else 1.0,
                reference_roles=roles,
                slide_index=f"{number} of {len(self.texts)}",  # 50 §6's fill convention
                slide_text=text,
                # D46 (FR-304/FR-308): the two panel-mapping slots — both empty for unbound or
                # brief-driven decks, and the template's "(ignore if empty)" lines stay silent.
                visual_brief=self._visual_brief(number),
                slide_panel_source=self._panel_source_line(number))
            context["style_dna"] = self.dna  # FR-189: the one block that never varies
            context["render_prompt"] = self._guided(context["render_prompt"], number)
            prompt = env.engine.render(ROLE_SLIDE, context,
                                       profile=env.config.models.image_profile,
                                       max_chars=self._limits.max_prompt_chars)  # 50 §7
        except (UnresolvedPlaceholderError, MissingTemplateError, ValueError, LookupError) as exc:
            env.log.error("prompt_assembly_failed", f"{self.entry.asset_id} slide {number}: {exc}",
                          asset_id=self.entry.asset_id, slide=number, role=ROLE_SLIDE)
            return None
        if plan is not None:  # FR-193: the retry repeats the preserve list and adds one line
            prompt = f"{prompt}\n\n{plan.instruction}"
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

    def _retry_plan(self, number: int) -> vision_check.RetryPlan:
        """FR-105's −40%: shorter text, one block, larger type — a different request, not a plea."""
        return vision_check.retry_plan(
            self.copy or CopySet(asset_id=self.entry.asset_id, language=self.entry.language),
            "carousel", self.env.config.run.text_budgets, slide_text=self.texts[number - 1])

    # ------------------------------------------------------------------------------ packaging

    def package(self) -> AssetRecord:
        """Terminal meta: what shipped, what it cost, which slides are missing (FR-73/74)."""
        entry, env = self.entry, self.env
        missing = [n for n in range(1, len(self.texts) + 1) if n not in self.delivered]
        fields: dict[str, Any] = {
            "actual_cost_usd": round(sum(o.cost_usd for o in self.outcomes), 6),
            "model_ids": [env.config.models.image, env.config.models.image_profile],
            "kie_job_ids": [o.task_id for o in self.outcomes if o.task_id],
            "job_submission_timestamp": next(
                (o.submitted_at for o in self.outcomes if o.submitted_at), None),
            "job_completion_timestamp": next(
                (o.completed_at for o in reversed(self.outcomes) if o.completed_at), None),
            "native_size_rendered": entry.aspect_ratio,  # FR-98: shipped as it came back
            "slide_count": len(self.delivered),
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
                         missing_slide_numbers=missing, detail="; ".join(self.reasons[:3]))
        entry.status = PlanEntryStatus.SUCCESS
        fields["event_id"] = env.log.event(
            "creative_delivered", f"{entry.asset_id} deck of {len(self.delivered)} slide(s)",
            asset_id=entry.asset_id, slides=len(self.delivered),
            cost_usd=fields["actual_cost_usd"], vision_check=fields["vision_check_result"].value)
        return self.folder.finish(**fields)

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
        """FR-308: the slide's English content directive, `""` whenever intelligence degraded —
        the `(ignore if empty)` line in the template makes the absence silent by design."""
        intel = self._intel()
        slide = intel.slide(number) if intel is not None else None
        return str(getattr(slide, "visual_brief", "") or "")

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

    def _note(self, reason: str, *, error: bool = False) -> bool:
        """Record one loss and log it. Always False, so callers can `return self._note(...)`."""
        self.reasons.append(reason)
        (self.env.log.error if error else self.env.log.warn)(
            "carousel_slide_lost", f"{self.entry.asset_id}: {reason}",
            asset_id=self.entry.asset_id)
        return False


__all__ = ["GUIDANCE_COVER", "GUIDANCE_SLIDE", "PANELS_TRUNCATED", "ROLE_ANCHOR", "ROLE_SLIDE",
           "ReserveKind", "Submit", "render_carousel"]
