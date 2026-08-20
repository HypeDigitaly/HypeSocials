"""CREATE — plan entries in, finished asset folders out. **All three formats, two waves.**

Module contract
---------------
Purpose: own everything between "this creative was approved" and "this creative is on disk" —
format dispatch, prompt assembly, reference attachment, the money around every submission, the
FR-203 ledger, the deadline's grace window, and packaging. The runner hands over entries and gets
back records; it never touches a template, a reference URL, a render body or a meta.yaml key.

Public API: `create(entries, env)` · `Env` · `Report` · `ledger_hooks(ledger)` · `GRACE_S`.

Invariants:
- **One money path.** Every submission — image, carousel slide, reel seed frame, Seedance clip —
  goes through the single `submit` callable built here, which owns FR-106 a/b/c (`projected` and
  `precommitted` `commit()`, `discretionary` `reserve()`), the profile lookup, the per-job
  projection (`budget.job_projection`) and exactly one `ledger.terminal()` line per submission.
  `carousel.py` and `reel.py` price nothing and write no ledger line — D49's per-deck gauntlet
  budget and runway check ask this module through `Env.price_job` / `Env.runway_ok` rather than
  deriving either themselves.
- **The post-render GATE is the gauntlet** (D49, FR-322–330, v2.2.0). Every format runs it:
  `gauntlet.run_deck` for a carousel, `gauntlet.run_single` for a standalone image and for a reel's
  seed frame. Each call site owns a `RerenderFn` closure — the money seam — and the gauntlet owns
  the loop, the critics and the three-tier terminal. A BLOCKED creative keeps every paid artifact
  (`packager.block()`, FR-74), is never published, and makes the run exit 1.
- **Spend tallies on submission, failures included** — a reservation that reached the provider is
  reconciled, never released; only a submission that never happened is released (20 §8).
- **One automatic resubmit per IMAGE job** (FR-317, v2.1.3/D48). A standalone image, a carousel
  slide or a reel seed frame that ends in TIMEOUT or a non-moderation failure is submitted once
  more, unchanged, as discretionary spend; a second failure is final. It is a NEW job with its own
  taskId and its own ledger lines — nothing re-polls a task id, and nothing resubmits a Seedance
  clip (FR-44). A timed-out attempt reconciles at a measured $0 (`_billed_usd`), so the pair costs
  one render rather than two.
- **A folder never holds media without meta** — `AssetFolder` writes `pending` meta at creation
  and rewrites it terminally, so every exit path (success, skip, interrupt, abandonment) leaves
  one whole state (NFR-21). A failed creative keeps its paid caption (FR-74).
- **Nothing new is ordered once `env.halted` is true**, and what is already in flight gets ONE
  ~30 s grace window before it is abandoned honestly, with its taskId in the ledger (FR-108/201).
- **Nothing is ordered that the deadline cannot pay for in TIME** (D51, v2.2.0). Beside the halt
  check, the same door refuses `discretionary` and `projected` work whose own job timeout plus the
  grace window no longer fits inside `deadline.remaining_s`: a job submitted with four minutes left
  and a ten-minute timeout is a purchased certainty of a timeout. The refusal is UNBILLED — nothing
  is reserved, nothing reaches the provider — and it carries `RenderFailCause.NO_RUNWAY`, which
  both FR-317 resubmit predicates exclude by name so a refusal can never burn a slide's one-shot.
  `precommitted` work is exempt (FR-106b): cap AND clock bookkeeping may never split a deck.
- **Text-to-image is the default route; a house style ships no pixels (D46/F3, v2.1.0)** — the
  style reference channel is excised, so `refs.attach()` uploads only a brief's OWN photos (D26)
  through the run-scoped memo (one upload per file per run, FR-200/244). The only other image a
  job may carry is one we made ourselves and chained inside a single creative: the carousel
  anchor slide (FR-94) and the reel's seed frame (FR-24). A failed upload drops that one
  reference, never the job.
- **A creative's visual authority is its `entry.style_key`** — `refs.style_of(entry, env)`
  resolves it against `env.styles` (the registry); the style's `render_prompt`/zones/DNA feed
  `build_context(style=...)` and the branding channels ride beside it (`branding_block` +
  the TEXT-block `wordmark`, FR-292 — never mixed, never both channels for one string).
- **An unresolved placeholder fails the creative BEFORE submission** (FR-260) — nothing malformed
  is ever paid for.
- **Kie's 402 is a whole-run condition** (FR-167): it is latched once and every remaining
  creative is skipped with "top up your Kie.ai credits" rather than each retrying a certainty.
- **A full disk stops downloading, run-wide** (10 §10): `env.disk_full` latches on the first
  `disk_full` packaging error and every later creative skips its download instead of thrashing
  the volume; the runner reads it back off `Report.disk_full`.

Do not: call Kie directly, name a Kie field, spell an asset path, re-derive a price, or let a
`CancelledError` escape `create()`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

from hypesocials import gauntlet, render
from hypesocials.budget import Budget, SpendCategory, job_projection
from hypesocials.config import BrandingConfig, Config
from hypesocials.models import (
    AssetRecord,
    Brief,
    CopySet,
    DegradationTag,
    PlanEntry,
    PlanEntryStatus,
    RenderOutcome,
    RenderOutcomeKind,
    RenderFailCause,
    RenderParams,
    RenderPriority,
    RenderRefs,
    TrendItem,
    VisionCheckResult,
)
from hypesocials.copywrite import CopyProvenance
from hypesocials.outputs import AssetFolder, Ledger, LogWriter, PackagingError, write_gallery
from hypesocials.prompts_engine import (
    MissingTemplateError,
    PromptEngine,
    UnresolvedPlaceholderError,
    build_context,
)
from hypesocials.util import Deadline, fit

# Both format modules back-import this package under TYPE_CHECKING only, so importing them here
# is safe and keeps the dispatch a plain name lookup (which is also what makes it fakeable).
from hypesocials.generate.refs import Reference, attach, branding_block, role_lines, style_of
from hypesocials.generate.refs import wordmark as wordmark_of
# FR-98 (v2.1.4): what the provider actually returned, read off the delivered file's own header.
# No decoder and no Pillow — four integers out of the first bytes of a PNG/JPEG/WebP.
from hypesocials.generate.pixels import native_size
# D49: "what was this frame ORDERED to be" — one contract builder for all three formats.
from hypesocials.generate import contracts
from hypesocials.generate.carousel import GAUNTLET_CRAFT, GAUNTLET_DEGRADED, render_carousel
from hypesocials.generate.reel import render_reel

#: The one image role post-pivot (F16's merged template).
ROLE_IMAGE = "image_post.md"

#: FR-108's "one short grace poll (~30 s)": at the deadline — or at the first Ctrl+C (FR-201) —
#: outstanding jobs get exactly this long to land, because work seconds from completing is work
#: already paid for. Whatever is still running afterwards is abandoned and left unclaimed at Kie,
#: which is the accepted, stated cost. Never a second window, and never a resubmission FROM HERE:
#: the grace window is the run stopping, and FR-317's single image resubmit is refused once
#: `env.halted` is true precisely so a halt cannot order new work (v2.1.3/D48).
GRACE_S = 30.0
#: How often `_drain` re-reads `env.halted` while creatives run; the deadline is a soft ceiling
#: (FR-108), so half a second of slack costs nothing and a timer beats a busy loop.
_HALT_POLL_S = 0.5

#: Set for the duration of one creative's submission so the FR-203 ledger hooks — which the
#: render seam calls with a request token and nothing else — can name the asset the token bought.
_CURRENT_ASSET: ContextVar[str] = ContextVar("_hypesocials_current_asset", default="")
#: asset_id -> the taskId of its latest submission that has not yet reached a terminal line. It
#: exists for one reason: an abandoned creative's ledger line can name the job that is still
#: running at Kie (FR-108/203). Cleared per run by `ledger_hooks()`.
_OPEN_TASKS: dict[str, str] = {}
#: asset_id -> `_Tally`: what this creative has already SPENT and SUBMITTED, accumulated at the
#: money door. It exists for the one path that cannot reconstruct it — `_abandon`, which runs
#: inside a `CancelledError` and holds no outcome at all — so an interrupted creative's meta.yaml
#: still names its jobs, its timestamps and its money instead of filing $0 and no ids against work
#: the operator was really billed for (FR-73/FR-108). Cleared per run by `ledger_hooks()`.
_TALLIES: dict[str, _Tally] = {}

_HALTED = "halted — the run stopped ordering new work (FR-108/201)"
_CREDITS = "kie_credits_exhausted — top up your Kie.ai credits (FR-167)"
#: D51's refusal, spelled once: what was refused, how much clock it needed and how much was left.
#: Read by an operator in run.log and by `carousel._submit`, which turns it into the deck's own
#: "nothing was ordered" note — so it must state the arithmetic rather than merely assert it.
_NO_RUNWAY = ("no_runway — this {job} job needs {need:.0f}s (its own timeout plus the {grace:.0f}s "
              "grace window) and the run deadline has {left:.0f}s left, so it was never submitted "
              "and nothing was billed (D51/FR-108)")


@dataclass(slots=True)
class _Tally:
    """One creative's running submission receipt — money, jobs and timestamps, as they happen.

    Every other terminal path holds the outcomes it needs and builds this block itself. The
    ABANDONED path cannot: it runs inside a `CancelledError` raised while a job is still in flight,
    so the only truthful account of what that creative already bought lives here, written as each
    submission passed through the money door.

    `cost_usd` mirrors `budget.reconcile` exactly — the provider's own figure when it reported one,
    the reservation's estimate when it did not (FR-85) — plus `open_usd`, the estimate still held
    against the job that never came back. A run summary counts that held reservation too, so meta
    and the summary agree rather than differing by one render.
    """

    cost_usd: float = 0.0
    open_usd: float = 0.0  # reserved for a submission with no terminal line yet
    job_ids: list[str] = field(default_factory=list)
    submitted_at: str | None = None
    completed_at: str | None = None

    def meta(self) -> dict[str, Any]:
        """The FR-73 cost/timing block, named exactly as `AssetRecord` spells it."""
        return {"actual_cost_usd": round(self.cost_usd + self.open_usd, 6),
                "kie_job_ids": list(self.job_ids),
                "job_submission_timestamp": self.submitted_at,
                "job_completion_timestamp": self.completed_at}


@dataclass(slots=True)
class Env:
    """Everything constant across one run's creatives, threaded once instead of per call."""

    config: Config
    run_dir: Path
    engine: PromptEngine
    budget: Budget
    log: LogWriter
    ledger: Ledger
    trends: Mapping[str, TrendItem] = field(default_factory=dict)
    copy: Mapping[str, CopySet] = field(default_factory=dict)
    #: FR-298: `asset_id -> CopyProvenance(post_id, refs)` — which `SourcePost` each creative
    #: quoted and which exact strings (`{slot: "P<n>.<kind>[.<i>]"}`); `_record` copies both onto
    #: the AssetRecord. Empty for override briefs and degrade paths — there was nothing quoted.
    copy_provenance: Mapping[str, CopyProvenance] = field(default_factory=dict)
    #: `CopyResult.tags` — `asset_id -> the DegradationTags the copy stage earned this creative`
    #: (FR-99's `copy_degraded`, FR-101's `text_trimmed`, A20's `no_onimage_text`, A21's
    #: the audit tags). ONE field rather than one frozenset per tag: the copy stage is
    #: free to grow a new degradation without a new field here and a new branch in `_record`.
    copy_tags: Mapping[str, Sequence[DegradationTag]] = field(default_factory=dict)
    #: FR-200/191: `asset_id -> ((path, kind), …)` — the provenance that picks each attachment's
    #: role line (`refs.py`, contracts item 11). Post-D46 the only kind the runner produces is
    #: `"brief"`: the style reference channel is excised (F3), so a meta-style contributes prose
    #: to the prompt and nothing to the upload memo.
    local_refs: Mapping[str, Sequence[tuple[Path, str]]] = field(default_factory=dict)
    campaign_briefs: Mapping[str, Brief] = field(default_factory=dict)  # FR-144/145, by name
    niche_descriptor: str = ""  # copy-side (audience included): the analyst and copywriter only
    niche_visual_world: str = ""  # A15: `niche.visual_world` alone — the render roles
    llm_call: Any = None  # metered `StructuredCall` for the D49 gauntlet critics; None = off
    #: D49's two money-door SEAMS, wired by `create()` and read by the format modules' `RerenderFn`
    #: closures. They exist so `carousel.py` and `reel.py` can measure a per-deck gauntlet budget
    #: and D51's runway WITHOUT importing `budget` or touching `env.budget` — their module contracts
    #: ("never price a job") stand exactly as written, because the price and the clock are ASKED of
    #: the module that owns them rather than re-derived. `None` on both (a preview, a unit test)
    #: makes the per-deck cap a no-op and the runway infinite, which is what those callers mean.
    price_job: Any = None  # `(entry, job) -> float` — `budget.job_projection`, bound to this config
    runway_ok: Any = None  # `(job) -> bool` — D51's gate, asked BEFORE a discretionary submission
    styles: Any = None  # `styles.StyleRegistry` — Any keeps generate free of a styles import;
    #   `refs.style_of` is the one resolver (the lazy-import precedent, contracts item 11)
    branding: BrandingConfig = field(default_factory=BrandingConfig)  # FR-292 brand selector +
    #   profiles; prompts_engine renders it, refs/carousel/reel read entry.branded beside it
    #: M6 (W3): the topic filter's guarded LLM `strip` verdicts, `trend_key -> brands`. Merged
    #: with `branding.competitors` into every prompt's `competitor_strings` — LLM-discovered
    #: brands must reach the RENDER prompt, not only the CopySet (Session-C obligation 2).
    strip_brands: Mapping[str, Sequence[str]] = field(default_factory=dict)
    #: FR-306 (D46): `post_id -> slide_intel.SlideIntel` for every bound carousel source post.
    #: `Any`-typed like `styles` above — generate stays free of a sources import; carousel reads
    #: it duck-typed for per-slide `visual_brief` lines (FR-308), and T3.3's `_record` merges it
    #: into `panel_map`/`source_post` on meta.yaml. Empty = no intelligence ran (previews, tests,
    #: vision off) and every consumer degrades to the pre-D46 shape.
    slide_intel: Mapping[str, Any] = field(default_factory=dict)
    stop: asyncio.Event | None = None  # Ctrl+C: stop ORDERING new work (FR-201)
    deadline: Deadline | None = None  # the run's soft monotonic ceiling (FR-108/243)
    credits_exhausted: bool = False  # FR-167, latched once
    disk_full: bool = False  # 10 §10, latched once: further downloads stop run-wide
    # --- FR-299 (D45): the RENDER phase must never be silent past `heartbeat_s`. `say` is the
    # runner's console seam (identical bytes to run.log); `pulse` is the run's ONE silence clock
    # (any printed line anywhere resets it). Both None keeps this module console-mute — previews
    # and unit tests never wire them. Counters are mutated by `_submit` only.
    say: Any = None
    pulse: Any = None  # util.Pulse — Any keeps generate free of a util type at the seam
    heartbeat_s: float = 30.0  # resolved cadence: 30 interactive / 90 --yes / 15 verbose
    jobs_expected: int = 0  # the runner's pre-computed submission forecast (heartbeat denominator)
    jobs_submitted: int = 0
    jobs_done: int = 0  # reached a terminal outcome, success or not
    jobs_ok: int = 0  # terminal AND usable — the RENDER closing header's `ok` count

    @property
    def halted(self) -> bool:
        """True once Ctrl+C landed or the run deadline elapsed — every module re-reads this
        before each submission, so an interrupt costs at most one in-flight job."""
        return bool(self.stop is not None and self.stop.is_set()) or bool(
            self.deadline is not None and self.deadline.expired)

    def competitor_strings_for(self, entry: PlanEntry) -> tuple[str, ...]:
        """M6, resolved ONCE for every render role: the config blocklist (fail-closed) plus the
        filter's guarded LLM strips for THIS creative's topic. Every `build_context` call in this
        package passes exactly this, so no prompt path can miss an LLM-discovered brand."""
        return (*map(str, self.branding.competitors),
                *map(str, self.strip_brands.get(entry.trend_key or "", ())))


@dataclass(slots=True)
class Report:
    """What landed on disk: one record per entry plus the trends that earned a history line."""

    records: dict[str, AssetRecord] = field(default_factory=dict)
    packaged_trends: set[str] = field(default_factory=set)  # FR-82: packaged creatives only
    disk_full: bool = False  # 10 §10: further downloads stop rather than thrash a full disk


def ledger_hooks(ledger: Ledger) -> tuple[Any, Any]:
    """FR-203's intent-before-call hooks, bound to this run's ledger.

    The render seam deliberately knows nothing about asset ids, so the asset travels in a
    context variable set around each submission; a token whose response is lost still gets its
    `submit_unknown` line, which is the exact case the ledger exists for.
    """
    _OPEN_TASKS.clear()
    _TALLIES.clear()

    def on_intent(request_token: str) -> None:
        ledger.intent(_CURRENT_ASSET.get() or "unknown", request_token)

    def on_submitted(request_token: str, task_id: str | None) -> None:
        asset = _CURRENT_ASSET.get() or "unknown"
        if task_id:  # remembered until its terminal line, so an abandon can still name the job
            _OPEN_TASKS[asset] = task_id
        ledger.submitted(asset, request_token, task_id)

    return on_intent, on_submitted


async def create(entries: Sequence[PlanEntry], env: Env) -> Report:
    """Build every approved creative concurrently and package the rest honestly.

    Concurrency is bounded inside `render.run()` by the priority permit gate, so every entry
    starts at once and the gate decides how many jobs are actually in flight (FR-25). Nothing
    raised — or cancelled — inside one creative can reach another: each returns a terminal record.
    """
    report = Report()
    # D49: bind the two money-door seams to THIS run before any format module can ask them. Done
    # here rather than at `Env` construction so every caller — the runner, a preview, a test that
    # builds an `Env` by hand — gets them without having to know they exist.
    env.price_job = env.price_job or partial(job_projection, env.config)
    env.runway_ok = env.runway_ok or (
        lambda job: _runway_refusal(env, job, "discretionary") is None)
    if not entries:
        return report
    tasks = [asyncio.create_task(_one(entry, env, report), name=f"create:{entry.asset_id}")
             for entry in entries]
    for record in await _drain(tasks, env):
        report.records[record.asset_id] = record
    report.disk_full = env.disk_full
    return report


#: FR-299: the first render heartbeat is suppressed this long after the wait begins — a healthy
#: fast batch stays heartbeat-free even under the verbose 15 s cadence (contracts item 16).
_FIRST_HEARTBEAT_RENDER_S = 20.0


def _heartbeat_line(env: Env, elapsed_s: float) -> str:
    """FR-299's render heartbeat, read straight off the permit gate — never off a guess."""
    running_w1, running_w2, queued = render.gate_stats()
    total = max(env.jobs_expected, env.jobs_submitted)
    minutes, rest = divmod(int(elapsed_s), 60)
    stamp = f"{minutes}m{rest:02d}s" if minutes else f"{int(elapsed_s)}s"
    return (f"          render {env.jobs_done}/{total} done, "
            f"{running_w1 + running_w2} running ({running_w1} w1, {running_w2} w2), "
            f"{queued} queued ... {stamp}")


async def _drain(tasks: list[asyncio.Task[AssetRecord]], env: Env) -> list[AssetRecord]:
    """Wait for every creative, then honour FR-108's single grace window.

    Ordering already stops the moment `env.halted` flips — every module re-reads it before each
    submission. What is left is the in-flight work, and it gets exactly one ~30 s window to land
    before it is cancelled: the entry goes terminal as `abandoned` with its taskId in the ledger,
    and the job is left to complete unclaimed at Kie (FR-108's stated cost). Never resubmitted,
    never awaited past the grace, and cancellation never escapes this function.

    This poll loop is ALSO the FR-299 render heartbeat's hook (§1.10): a silence-breaker, not a
    ticker — it prints only when `env.pulse` reports nothing has printed for `heartbeat_s`, and
    the print itself re-stamps the clock through the runner's `say` seam.
    """
    pending: set[asyncio.Task[AssetRecord]] = set(tasks)
    shown = False
    wait_started = time.monotonic()
    while pending and not env.halted:
        done, pending = await asyncio.wait(pending, timeout=_HALT_POLL_S)
        if done and not shown:  # FR-76: the first creatives are reviewable while reels still run
            shown = True  # NFR-22 is inside `write_gallery` — it returns None, it never raises
            write_gallery(env.run_dir, title=env.config.output.gallery.title, log=env.log)
            if env.say is not None:  # FR-297f: the gallery path prints the moment it exists
                env.say(f"  gallery   {env.run_dir / 'gallery.html'}")
        if (pending and env.say is not None and env.pulse is not None
                and env.pulse.due(wait_started=wait_started,
                                  suppress_s=_FIRST_HEARTBEAT_RENDER_S)):
            env.say(_heartbeat_line(env, time.monotonic() - wait_started))
    if pending:
        grace_line = (f"{len(pending)} creative(s) still in flight — one {GRACE_S:.0f}s grace "
                      "window, then they are abandoned and left unclaimed at Kie (FR-108)")
        env.log.warn("grace_poll", grace_line, in_flight=len(pending))
        if env.say is not None:
            env.say(f"  {grace_line}")
        _, pending = await asyncio.wait(pending, timeout=GRACE_S)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.wait(pending)  # each wrapper answers a cancellation with a terminal record
    return [task.result() for task in tasks if not task.cancelled()]


# --------------------------------------------------------------------------- one creative


async def _one(entry: PlanEntry, env: Env, report: Report) -> AssetRecord:
    """One plan entry, from folder creation to terminal meta. Never raises, never cancels out."""
    folder = AssetFolder(env.run_dir, _record(entry, env))
    copyset = env.copy.get(entry.asset_id)
    if copyset is not None:
        try:  # the copy was already paid for; a failed write must not cost the whole creative
            folder.write_caption(copyset.caption, copyset.hashtags)
        except PackagingError as exc:
            env.log.error("caption_write_failed", f"{entry.asset_id}: {exc}",
                          asset_id=entry.asset_id)
    brief = env.campaign_briefs.get(entry.brief_name or "")
    for path in (brief.reference_image_paths if brief else ()):
        try:  # FR-71: a brief's own pictures ship in the asset's `refs/`, beside what they made
            folder.add_reference(path)
        except PackagingError as exc:
            env.log.warn("reference_copy_failed",
                         f"{entry.asset_id}: {Path(path).name} not copied into refs/ ({exc})",
                         asset_id=entry.asset_id, reference=Path(path).name)
    try:
        return await _dispatch(entry, env, folder, report)
    except asyncio.CancelledError:
        # The grace window closed on an in-flight job. Every write in `_abandon` is synchronous,
        # so this folder still lands terminal while the task unwinds (NFR-21, FR-108).
        return _abandon(entry, env, folder)
    finally:
        # The running receipt exists for the abandon path and dies with the creative: a stale
        # tally would attribute this run's money to the next run's asset of the same id.
        _TALLIES.pop(entry.asset_id, None)


async def _dispatch(entry: PlanEntry, env: Env, folder: AssetFolder,
                    report: Report) -> AssetRecord:
    """Pre-checks, then the one branch by format. Each module owns its own chain from there.

    Each early exit records what EXISTS at that point and not one field more: no job ran, so there
    are no job ids, no timestamps, no model ids and no measured size — but there is a $0 spend, the
    requested ratio, and above all an `event_id`. FR-73 says a terminal meta.yaml points at the
    run-log line that explains it, and these three skips were the only terminals in the module that
    pointed at nothing, which made a folder full of `pending`-shaped nulls the operator's only
    account of why a planned creative never happened.
    """
    if entry.status is PlanEntryStatus.SKIPPED_BUDGET:
        reason = entry.skip_reason or "trimmed to fit the spend cap (FR-28/FR-106)"
        return folder.skip(reason, DegradationTag.SKIPPED_BUDGET,
                           **_unspent(entry, env, "creative_skipped", reason))
    if entry.status is not PlanEntryStatus.PENDING:
        reason = entry.skip_reason or f"not generated ({entry.status.value})"
        return folder.skip(reason, **_unspent(entry, env, "creative_skipped", reason))
    if env.credits_exhausted:
        return _fail(entry, env, folder, _CREDITS)
    if env.halted:
        entry.status = PlanEntryStatus.ABANDONED
        entry.skip_reason = "interrupted_before_submission"
        reason = "interrupted before submission — nothing was ordered for this creative"
        return folder.skip(reason, DegradationTag.ABANDONED,
                           **_unspent(entry, env, "abandoned", reason))

    submit = _submitter(env)
    if entry.creative_format == "carousel":
        record = await render_carousel(entry, env, folder, submit=submit)
    elif entry.creative_format == "reel":
        record = await render_reel(entry, env, folder, submit=submit)
    else:
        record = await _image(entry, env, folder, submit)
    if entry.status is PlanEntryStatus.SUCCESS and entry.trend_key:
        report.packaged_trends.add(entry.trend_key)  # FR-82: packaged creatives only
    return record


def _resubmittable(outcome: RenderOutcome | None) -> bool:
    """FR-317 (v2.1.3, D48): does this IMAGE job's ending sanction exactly one more attempt?

    A moderation refusal is excluded by name — FR-97 owns that failure, and re-asking the identical
    question buys the identical no. A declined submission is excluded because nothing was ordered.
    Everything else terminal (a timeout, a provider error, an empty or unreachable result) is the
    same request that simply did not come back, so it is worth sending once more.

    A runway refusal (`NO_RUNWAY`, D51) is excluded by name for a different reason again: it is the
    one terminal cause in the enum that describes a job which never existed. Nothing was ordered,
    nothing was billed, and the clock that refused it will only be shorter on a second ask — so
    resubmitting would buy the identical refusal while burning the single attempt FR-317 grants a
    job that really did fail.

    Video jobs never reach this predicate: `_submit_clip` is Seedance's only door and FR-44 keeps
    "a timed-out video job is never resubmitted" exactly as it was.
    """
    return (outcome is not None and outcome.kind is not RenderOutcomeKind.SUCCESS
            and outcome.fail_cause is not RenderFailCause.MODERATION
            and outcome.fail_cause is not RenderFailCause.NO_RUNWAY)


async def _image(entry: PlanEntry, env: Env, folder: AssetFolder, submit: Any) -> AssetRecord:
    """One image: assemble, submit, FR-97's retry, FR-317's resubmit, D49's gauntlet."""
    attached = await attach(entry, env, folder)
    urls = [ref.url for ref in attached]
    prompt = _assemble(entry, env, attached)
    if prompt is None:
        return _fail(entry, env, folder, "prompt_assembly_failed — unresolved placeholder (FR-260)")
    params = RenderParams(prompt=prompt, aspect_ratio=entry.aspect_ratio,
                          resolution=env.config.image_resolution(entry.platform))  # FR-342
    try:
        outcome = await submit(entry, params, RenderRefs(image_urls=urls), job="image",
                               priority=RenderPriority.WAVE1, kind="projected",
                               label=f"image render · {entry.asset_id}")
        if (outcome is not None and outcome.kind is not RenderOutcomeKind.SUCCESS
                and outcome.fail_cause is RenderFailCause.MODERATION and urls):
            env.log.warn("moderation_retry",
                         f"{entry.asset_id}: content-policy refusal; one reference-free retry "
                         "(FR-97)", asset_id=entry.asset_id, detail=outcome.fail_message)
            # The refused job was billed on submission and already has its own terminal ledger
            # line from `submit` — the ledger shows both taskIds, not only the one that survived.
            retry = await submit(entry, params, RenderRefs(), job="image",
                                 priority=RenderPriority.WAVE1, kind="discretionary",
                                 label=f"moderation retry · {entry.asset_id}")
            if retry is not None:
                folder.mark(DegradationTag.REFS_DROPPED_MODERATION)
                outcome, urls = retry, []
        # FR-317: a timeout or an ordinary provider failure is the same request that never came
        # back, so it goes once more — as discretionary spend the cap may decline, after a fresh
        # read of `env.halted` (the first attempt may have burned the whole 600 s timeout inside
        # the window where Ctrl+C landed). Exactly one: whatever the second attempt says is final,
        # and the timed-out first attempt already reconciled at $0 (`_billed_usd`).
        if _resubmittable(outcome) and not env.halted and not env.credits_exhausted:
            cause = outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value
            env.log.warn("image_job_resubmit",
                         f"{entry.asset_id}: {cause} "
                         f"({outcome.fail_message or 'no usable result'}) — resubmitting the SAME "
                         "job once (FR-317, attempt 2 of 2); a second failure is final",
                         asset_id=entry.asset_id, cause=cause, attempt=2,
                         task_id=outcome.task_id, detail=outcome.fail_message)
            again = await submit(entry, params, RenderRefs(image_urls=urls), job="image",
                                 priority=RenderPriority.WAVE1, kind="discretionary",
                                 label=f"resubmit · {entry.asset_id}")
            if again is not None:
                outcome = again
    except render.KieOutOfCredits as exc:
        env.credits_exhausted = True
        return _fail(entry, env, folder, f"{_CREDITS} ({exc})")
    if outcome is None:
        return _fail(entry, env, folder, "skipped_budget — the cap declined this submission",
                     DegradationTag.SKIPPED_BUDGET)
    if outcome.kind is not RenderOutcomeKind.SUCCESS or not outcome.result_urls:
        # FR-242: a `success` with no usable result is a failure that lies — treated as a failure.
        cause = (outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value)
        env.log.error("render_failed", f"{entry.asset_id}: {cause} — "
                      f"{outcome.fail_message or 'no usable result'}", asset_id=entry.asset_id,
                      task_id=outcome.task_id, cost_usd=round(outcome.cost_usd, 6))
        return _fail(entry, env, folder, f"{cause}: {outcome.fail_message or 'no usable result'}"
                     f" (job {outcome.task_id or 'unknown'})", cost=outcome.cost_usd,
                     outcome=outcome, referenced=bool(urls))
    if env.disk_full:  # 10 §10: downloads stopped run-wide rather than thrash a full disk
        return _fail(entry, env, folder, "disk_full: downloads stopped for this run",
                     cost=outcome.cost_usd, outcome=outcome, referenced=bool(urls))
    try:  # the bytes stop being a borrowed 24 h URL and become the operator's file
        stored = await folder.store_render(outcome.result_urls[0])
    except PackagingError as exc:
        if exc.reason == "disk_full":  # the one failure that outlives this creative
            env.disk_full = True
        return _fail(entry, env, folder, f"{exc.reason}: {exc}", cost=outcome.cost_usd,
                     outcome=outcome, referenced=bool(urls))
    report, extra, delivered = await _gauntlet_image(entry, env, folder, submit, attached, stored)
    if report is not None:  # the operator-readable critic record, beside the artifacts
        folder.write_gauntlet_report(contracts.report_rows(report, asset_id=entry.asset_id))
    verdict = contracts.verdict_result(report, rerendered=bool(report and report.rerenders))
    cost = outcome.cost_usd + sum(job.cost_usd for job in extra)
    if report is not None and report.result == "blocked":
        # FR-325: the image rendered and is being WITHHELD, not lost. Every paid artifact stays on
        # disk (FR-74) and `PlanEntryStatus.BLOCKED` keeps it out of the history window, out of the
        # `latest` pointer's satisfaction test and inside the run's exit-1 answer.
        reason = ("gauntlet_blocked: the post-render critic panel found standing defect(s) after "
                  f"{len(report.rounds)} round(s); the image is kept and not published (FR-325). "
                  "See BLOCKED.txt and GAUNTLET_REPORT.yaml")
        entry.status = PlanEntryStatus.BLOCKED
        entry.skip_reason = entry.skip_reason or reason
        return folder.block(
            reason, contracts.blocked_text(report),
            actual_cost_usd=round(cost, 6),
            model_ids=[env.config.models.image_edit if attached else env.config.models.image,
                       env.config.models.image_profile],
            kie_job_ids=[job.task_id for job in (outcome, *extra) if job.task_id],
            job_submission_timestamp=outcome.submitted_at,
            job_completion_timestamp=(extra[-1].completed_at if extra else "")
            or outcome.completed_at,
            native_size_rendered=native_size(delivered, entry.aspect_ratio, log=env.log,
                                             asset_id=entry.asset_id),
            gauntlet=contracts.report_meta(report), vision_check_result=verdict,
            event_id=env.log.error("gauntlet_blocked", f"{entry.asset_id}: {reason}",
                                   asset_id=entry.asset_id, rounds=len(report.rounds),
                                   rerenders=report.rerenders, cost_usd=round(cost, 6)))
    if report is not None and report.craft_only:
        folder.mark(GAUNTLET_CRAFT)  # FR-325 tier 3: craft-only failures ship, tagged
    if report is not None and (report.degraded_gate or report.result == "degraded"):
        folder.mark(GAUNTLET_DEGRADED)  # any degraded ship is tagged: D3, an FR-325 demotion,
        #   or a contract-tier `fail_action: degrade` outcome (2026-08-20 gap fix)
    entry.status = PlanEntryStatus.SUCCESS
    return folder.finish(
        actual_cost_usd=round(cost, 6),
        # FR-270, honestly (v2.1.4): this creative's route was decided by whether it carried
        # references (FR-241), so the id recorded is the one that was actually used — `image_edit`
        # for a reference-bearing job, `image` for a reference-free one. Recording `models.image`
        # for every image was a lie the moment the dual route went live: glz0's reference-bearing
        # renders all claim a text-to-image id they never touched.
        model_ids=[env.config.models.image_edit if attached else env.config.models.image,
                   env.config.models.image_profile],
        kie_job_ids=[job.task_id for job in (outcome, *extra) if job.task_id],
        job_submission_timestamp=outcome.submitted_at,
        job_completion_timestamp=(extra[-1].completed_at if extra else "") or outcome.completed_at,
        # FR-98: shipped exactly as it came back — and now RECORDED as it came back. `native_size`
        # reads the delivered file's own header, so a 1536x1024 answer to a 1:1 request is stated
        # rather than restated as "1:1" (audit R4), and warns once.
        native_size_rendered=native_size(delivered, entry.aspect_ratio, log=env.log,
                                         asset_id=entry.asset_id),
        # FR-328 (spec §6): the gate's own receipt, on every terminal path it touched.
        gauntlet=contracts.report_meta(report),
        vision_check_result=verdict,
        event_id=env.log.event("creative_delivered", f"{entry.asset_id} rendered",
                               asset_id=entry.asset_id, task_id=outcome.task_id,
                               cost_usd=round(cost, 6), vision_check=verdict.value,
                               gauntlet=(report.result if report is not None else "not_run"),
                               duration_ms=int(outcome.elapsed_s * 1000)))


async def _gauntlet_image(
    entry: PlanEntry, env: Env, folder: AssetFolder, submit: Any,
    attached: Sequence[Reference], stored: Path,
) -> tuple[Any, list[RenderOutcome], Path]:
    """D49 for a standalone image: `gauntlet.run_single` over the one frame that came back.

    Same loop, same critics, same three-tier terminal as a deck — the only differences are that
    there is no cross-frame consistency to judge and that the round ceiling is
    `run.gauntlet.rounds_max_image` (spec §4: a lone frame that needs three rounds is a copy
    problem, not a render problem). `gauntlet.run_single` takes that minimum itself.

    Returns the report, every extra `RenderOutcome` the fix loop bought (for cost and job ids) and
    the path of the file that is actually SHIPPING — `stored`, or the fix re-render that replaced
    it, because meta records the delivered picture's real pixel size (FR-98).
    """
    if not contracts.gate_on(env):
        return None, [], stored
    copyset = env.copy.get(entry.asset_id) or CopySet(asset_id=entry.asset_id,
                                                      language=entry.language)
    style = style_of(entry, env)
    signature = wordmark_of(entry, env)
    # FR-322: the frame is judged against the words it was LOCKED to carry — headline, subline and,
    # on a branded entry, the wordmark that renders through the same TEXT block (B1). An unlisted
    # wordmark reads to a critic as an invented word; a listed one nobody ordered reads as missing.
    frame = contracts.frame_contract(
        1, "\n".join(part for part in (copyset.headline, copyset.subline) if part.strip()),
        style=style, signature=signature)
    contract = contracts.deck_contract(
        [frame], entry=entry, style=style, wordmark=signature,
        forbidden=contracts.forbidden_terms(competitors=env.competitor_strings_for(entry)))
    spent: list[float] = [0.0]
    bought: list[RenderOutcome] = []
    shipping = [stored]

    async def rerender(number: int, fix: str) -> gauntlet.RerenderResult:
        """The money seam (spec §1) for one image — every dollar decision in the fix loop.

        FR-317 exclusivity holds by construction: this is a FRESH submission with its own ledger
        rows, it is not routed through `_resubmittable`, and it is never itself resubmitted.
        """
        if env.halted:
            return gauntlet.RerenderResult(status="halted")
        if env.credits_exhausted:
            return gauntlet.RerenderResult(status="failed")
        projected = float(env.price_job(entry, "image")) if callable(env.price_job) else 0.0
        cap = float(env.config.run.gauntlet.deck_budget_usd or 0.0)
        if cap > 0 and spent[0] + projected > cap:
            env.log.warn("gauntlet_budget_stop",
                         f"{entry.asset_id}: the per-creative gauntlet budget ({cap:.2f}) is spent "
                         f"({spent[0]:.2f} used) — no further fix re-render is ordered",
                         asset_id=entry.asset_id, spent_usd=spent[0], cap_usd=cap)
            return gauntlet.RerenderResult(status="declined_deck_budget")
        if callable(env.runway_ok) and not env.runway_ok("image"):
            return gauntlet.RerenderResult(status="declined_runway")
        prompt = _assemble(entry, env, attached, copyset=copyset, extra=fix)
        if prompt is None:
            return gauntlet.RerenderResult(status="failed")
        try:
            again = await submit(
                entry, RenderParams(prompt=prompt, aspect_ratio=entry.aspect_ratio,
                                    resolution=env.config.image_resolution(entry.platform)),
                RenderRefs(image_urls=[ref.url for ref in attached]), job="image",
                priority=RenderPriority.WAVE1, kind="discretionary",
                label=f"gauntlet re-render · {entry.asset_id}")
        except render.KieOutOfCredits:
            env.credits_exhausted = True  # FR-167: the flagged image ships exactly as rendered
            return gauntlet.RerenderResult(status="failed")
        if again is None:
            return gauntlet.RerenderResult(status="declined_budget")
        if again.fail_cause is RenderFailCause.NO_RUNWAY:  # D51: unbilled, nothing was ordered
            return gauntlet.RerenderResult(status="declined_runway")
        bought.append(again)
        cost = float(again.cost_usd or 0.0) or projected
        spent[0] += cost
        if again.kind is not RenderOutcomeKind.SUCCESS or not again.result_urls:
            return gauntlet.RerenderResult(status="failed", cost_usd=cost)
        try:  # the fix re-render REPLACES the delivered file
            shipping[0] = await folder.store_render(again.result_urls[0])
        except PackagingError as exc:
            if exc.reason == "disk_full":
                env.disk_full = True
            return gauntlet.RerenderResult(status="failed", cost_usd=cost)
        return gauntlet.RerenderResult(
            status="delivered", cost_usd=cost,
            frame=gauntlet.FrameUnderTest(number=number, source=shipping[0]))

    report = await gauntlet.run_single(
        gauntlet.FrameUnderTest(number=1, source=stored), contract, rerender,
        cfg=env.config.run.gauntlet, call=env.llm_call, log=env.log, engine=env.engine)
    return report, bought, shipping[0]


# --------------------------------------------------------------------------- the money door


def _submitter(env: Env) -> Any:
    """This run's `submit` callable, matching `carousel.Submit` field for field."""
    return partial(_submit, env=env)


async def _submit(
    entry: PlanEntry, params: RenderParams, refs: RenderRefs, *, env: Env, job: str,
    priority: RenderPriority, kind: str, label: str,
) -> RenderOutcome | None:
    """The run's ONE metered door to `render.run` — money, profile and ledger, in that order.

    Owns FR-106 a/b/c: `projected` work `commit()`s inside the approved wave-1 projection,
    `precommitted` work (slides 2–N, the Seedance clip) `commit()`s unconditionally so cap
    bookkeeping can never split a deck, and `discretionary` work (moderation retries,
    vision-check re-renders) `reserve()`s and returns `None` when the cap declines it. Spend
    tallies on submission — a job that reached the provider is reconciled to its own reported
    cost, failures included; only a submission that never happened is released (20 §8).

    Also owns the profile (`clip` → `models.video_profile`, everything else →
    `models.image_profile`), the per-job projection (`budget.job_projection` — no caller prices
    anything), and exactly one FR-203 `terminal` ledger line per submission, including the
    moderation-refused and content-audit-failed attempts a caller then retries. What "its own
    reported cost" means for a job that reported nothing is `_billed_usd`'s single decision.

    `render.KieOutOfCredits` is re-raised after the reservation is released — callers latch
    `env.credits_exhausted` and package what they hold (FR-167). A halt is belt and braces: every
    caller pre-checks `env.halted`, so this only catches the race, and it returns a FAIL outcome
    without holding or spending anything.
    """
    if env.credits_exhausted:
        raise render.KieOutOfCredits(_CREDITS)
    if env.halted:
        return RenderOutcome(kind=RenderOutcomeKind.FAIL, fail_message=_HALTED)
    if (refusal := _runway_refusal(env, job, kind)) is not None:
        env.log.warn("no_runway", f"{entry.asset_id}: {label} — {refusal.fail_message}",
                     asset_id=entry.asset_id, job=job, kind=kind)
        return refusal
    profile = (env.config.models.video_profile if job == "clip"
               else env.config.models.image_profile)
    projected = job_projection(env.config, entry, job)
    tally = _TALLIES.setdefault(entry.asset_id, _Tally())
    if kind == "discretionary":  # FR-106c — the only spend the cap can still decline
        held = await env.budget.reserve(projected, label=label, category=SpendCategory.RENDER,
                                        asset_id=entry.asset_id)
        if held is None:
            env.log.warn("skipped_budget", f"{entry.asset_id}: {label} declined by the spend cap",
                         asset_id=entry.asset_id, projected_usd=projected)
            return None
    else:  # FR-106a/b — projected and pre-committed work is never refused here
        held = await env.budget.commit(projected, label=label, category=SpendCategory.RENDER,
                                       asset_id=entry.asset_id, kind=kind)
    token = _CURRENT_ASSET.set(entry.asset_id)
    env.jobs_submitted += 1
    tally.open_usd += projected  # held against a job with no terminal line yet (see `_Tally`)
    try:
        outcome = await render.run(profile, params, refs, priority)
    except render.KieOutOfCredits:
        await env.budget.release(held)  # nothing was submitted, so nothing was billed
        env.jobs_submitted -= 1
        tally.open_usd -= projected
        raise
    except render.RenderError as exc:  # seam misuse or an unknown profile: no job ever left
        await env.budget.release(held)
        env.jobs_submitted -= 1
        tally.open_usd -= projected
        env.log.error("render_seam_error", f"{entry.asset_id}: {exc}", asset_id=entry.asset_id)
        return RenderOutcome(kind=RenderOutcomeKind.FAIL, fail_message=str(exc))
    finally:
        _CURRENT_ASSET.reset(token)
    billed = _billed_usd(outcome)
    await env.budget.reconcile(held, billed)
    tally.open_usd -= projected  # settled: the same figure the budget just counted, never both
    tally.cost_usd += projected if billed is None else billed
    if outcome.task_id:
        tally.job_ids.append(outcome.task_id)
    tally.submitted_at = tally.submitted_at or outcome.submitted_at
    tally.completed_at = outcome.completed_at or tally.completed_at
    env.jobs_done += 1
    if outcome.kind is RenderOutcomeKind.SUCCESS and outcome.result_urls:
        env.jobs_ok += 1
    _OPEN_TASKS.pop(entry.asset_id, None)  # it reached a terminal state: nothing to abandon
    env.ledger.terminal(entry.asset_id, outcome.request_token or "", outcome.task_id,
                        outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value)
    if env.say is not None:  # FR-299: one event-driven terminal line per submission
        env.say(_job_line(entry, label, priority, outcome))
    return outcome


def _runway_refusal(env: Env, job: str, kind: str) -> RenderOutcome | None:
    """D51's runway gate: the unbilled `NO_RUNWAY` refusal, or `None` when the clock still fits.

    A render job has a timeout of its own — 600 s for an image, 1800 s for a Seedance clip — and
    the run has a soft deadline (FR-108). Submitting a ten-minute job with four minutes left buys
    a certainty: the job cannot land inside the window, the grace poll abandons it, and the money
    is spent on a taskId nobody will ever claim. So the door refuses it BEFORE the reservation,
    which is what makes the refusal free: no `commit`, no `reserve`, no provider call, no ledger
    line, `$0`.

    Two exemptions, both deliberate:

    * `precommitted` work is never refused (FR-106b). Slides 2–N and the Seedance clip a chain
      already anchored are the deck the operator paid for; stopping half of it on a clock would
      split a deck, which is the exact failure the pre-committed class exists to prevent. Those
      submissions keep their own `env.halted` check and the grace window as their protection.
    * A run with no deadline at all (`env.deadline is None` — previews, unit tests, an unbounded
      operator run) has infinite runway by definition and this gate never fires.
    """
    deadline = env.deadline
    if kind == "precommitted" or deadline is None:
        return None
    models = env.config.models
    need = float(models.video_job_timeout_s if job == "clip"
                 else models.image_job_timeout_s) + GRACE_S
    left = deadline.remaining_s
    if left >= need:
        return None
    return RenderOutcome(
        kind=RenderOutcomeKind.FAIL, fail_cause=RenderFailCause.NO_RUNWAY,
        fail_message=_NO_RUNWAY.format(job=job, need=need, grace=GRACE_S, left=left))


def _billed_usd(outcome: RenderOutcome) -> float | None:
    """What this submission is reconciled AT — a real figure, or `None` for FR-85's *estimated*.

    `None` means "the provider reported no billing data": `budget.reconcile` then lets the
    reservation's own estimate stand and flags the row `estimated_only` rather than inventing a
    number. That is the honest answer for a job that finished and simply came back without a
    `creditsConsumed` field — the work happened, only its price is unreported.

    It is the WRONG answer for a job that TIMED OUT, and that is what this helper exists to
    separate. `render/kie.py::_classify` builds a timeout outcome from an EMPTY record (no
    terminal state was ever read), so its `cost_usd` is a structural 0.0 rather than a reported
    one — and the falsy test this replaced (`outcome.cost_usd if outcome.cost_usd else None`)
    could not tell those two zeros apart. It read the timeout as missing data and booked the FULL
    per-job estimate as billed: run `20260813_143420_oyo4` reported $1.27 against $0.94 of real
    Kie spend for exactly that reason, on rows the summary then labelled `estimated_only`.

    A timed-out job delivered nothing and is reconciled at a measured 0.0. The residual risk is
    stated rather than hidden: the job may still complete unclaimed at Kie and bill later (the
    same aftermath FR-108's abandonment line names by taskId), in which case the run under-reports
    by that job — a bounded, visible gap, where the old behaviour over-reported every timeout by
    a whole render on every run.

    Every other outcome keeps the pre-existing reading, FR-85 semantics untouched: a genuine 0.0
    from a successful job is indistinguishable from an absent figure at this seam, so it stays
    `estimated_only`.
    """
    if (outcome.kind is not RenderOutcomeKind.SUCCESS
            and outcome.fail_cause is RenderFailCause.TIMEOUT):
        return 0.0
    return outcome.cost_usd if outcome.cost_usd else None


def _job_line(entry: PlanEntry, label: str, priority: RenderPriority,
              outcome: RenderOutcome) -> str:
    """`ok/failed · NN fmt · w1|w2 · what · dur · $cost` — the §1.10 per-job console line.

    `what` is the submission label's descriptive half (`carousel slide 4/5`, `reel clip`,
    `moderation retry`), which is the honest per-job identity this seam already carries; a failed
    job shows its cause instead of a price, because the cause is what the operator acts on.
    """
    ordinal = entry.asset_id.rsplit("_", 1)[-1]
    wave = "w1" if priority is RenderPriority.WAVE1 else "w2"
    what = label.split(" · ", 1)[0]
    ok = outcome.kind is RenderOutcomeKind.SUCCESS and bool(outcome.result_urls)
    if ok:
        return (f"          ok      {ordinal:>2} {entry.creative_format:<8} {wave}  "
                f"{what[:20]:<20} {outcome.elapsed_s:>4.0f}s  ${outcome.cost_usd:.3f}")
    cause = outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value
    detail = (outcome.fail_message or "no usable result").replace("\n", " ")
    head = f"          failed  {ordinal:>2} {entry.creative_format:<8} {wave}  "
    return head + fit(f"{what}: {cause} — {detail}", 78 - len(head))


# --------------------------------------------------------------------------- inputs


def _assemble(entry: PlanEntry, env: Env, attached: Sequence[Reference], *,
              copyset: CopySet | None = None, budget_scale: float = 1.0,
              extra: str = "") -> str | None:
    """The finished render prompt, or `None` when it cannot be filled (FR-17/94/96, FR-260)."""
    role = ROLE_IMAGE  # F16: one merged image role; override briefs override INSIDE it (M14)
    style = style_of(entry, env)  # None under an override brief or with no registry
    profile = render.get_profile(env.config.models.image_profile)
    context = build_context(
        trend=env.trends.get(entry.trend_key or ""),
        style=style,  # FR-290/291: the registry is the visual authority
        copy=copyset or env.copy.get(entry.asset_id),
        budget_scale=budget_scale,  # FR-105's −40% retry states the budget it actually carries
        # FR-144/145: `override` visual directives REPLACE render_prompt/layout_zones; `blend`
        # states the precedence — style wins visuals, brief wins message and CTA.
        campaign_brief=env.campaign_briefs.get(entry.brief_name or ""),
        creative_format="image",
        niche_descriptor=env.niche_descriptor,
        niche_visual_world=env.niche_visual_world,  # A15: render-side art direction
        branding_block=branding_block(entry, env, style),  # FR-292 channel 2 (never the wordmark)
        wordmark=wordmark_of(entry, env),  # FR-292 channel 1: TEXT-block only, branded only (B1)
        # M6: the deterministic blocklist AND the filter's LLM-proposed strips for this topic
        # reach every render prompt — the CopySet-level strip alone is not the whole guarantee.
        competitor_strings=env.competitor_strings_for(entry),
        text_budgets=env.config.run.text_budgets,
        reference_roles=role_lines(attached),  # FR-191: one line per attachment, by provenance
    )
    # The old reference-free content-sentence splice is dead: `image_post.md` carries its own
    # `{{content_sentence}}` slot beside `{{render_prompt}}` (F16), so no manual prepend.
    try:
        prompt = env.engine.render(role, context, profile=profile.name,
                                   max_chars=profile.limits.max_prompt_chars,  # 50 §7
                                   # FR-193: the vision retry repeats the preserve list and adds
                                   # one line — through the engine, so it is INSIDE the length
                                   # guarantee. Appended afterwards (as it was until v2.1.4) it
                                   # pushed an at-the-limit prompt over the provider's hard wall
                                   # with no guard event and bought a certain HTTP 500.
                                   suffix=extra)
    except (UnresolvedPlaceholderError, MissingTemplateError, ValueError, LookupError) as exc:
        env.log.error("prompt_assembly_failed", f"{entry.asset_id}: {exc}",
                      asset_id=entry.asset_id, role=role)
        return None
    env.log.event("render_prompt_assembled", f"{entry.asset_id} prompt ready", verbose_only=True,
                  asset_id=entry.asset_id, role=role, references=len(attached), prompt=prompt)
    return prompt


def _record(entry: PlanEntry, env: Env) -> AssetRecord:
    """The `pending` meta.yaml this creative starts life with — FR-73 field for field.

    This is also the ONE place the three provenance stages are joined into a single document
    (FR-73 as amended v2.1.0): the PLAN's bound source post (`entry.source_post_id`), the COPY
    stage's panel map (`CopyProvenance` — which of our slides quoted which source panel, and under
    which ref label), and the slide-INTELLIGENCE reading of that same deck (`env.slide_intel` —
    what each source panel looked like, and where its downloaded picture lives). Each of the three
    is independently optional and each absence degrades to the pre-D46 shape rather than costing
    the creative: no bound post means `source_post: null` and no rows, no intelligence means every
    row still exists with an empty `visual_brief` and a null `source_image`.

    FR-309's gallery card is built from exactly these fields and nothing else, which is why the
    join happens here, once, instead of in the page writer: the gallery reads `meta.yaml`, it does
    not re-derive provenance and it never opens `source.yaml`.
    """
    trend = env.trends.get(entry.trend_key or "")
    prov = env.copy_provenance.get(entry.asset_id)
    # The bound post is the PLAN's (FR-304), not the copy stage's: an image or a reel may well
    # quote a post without binding its deck, and those carry no `source_post` by contract. The
    # provenance fallback is belt-and-braces for a panel map that arrived without the entry field.
    post_id = str(entry.source_post_id or "").strip() or (
        str(prov.post_id) if prov and prov.panel_map else "")
    bound = _bound_post(post_id, trend)
    intel = env.slide_intel.get(post_id) if post_id else None
    degradations: list[DegradationTag] = list(env.copy_tags.get(entry.asset_id, ()))
    for tag in _intel_tags(intel):  # FR-306: `vision_transcribed` / `vision_unavailable`
        if tag not in degradations:  # the copy stage may already have carried one
            degradations.append(tag)
    # FR-334/FR-337 (v2.4.0, D56): the ONE batched style matcher never spoke, so every entry in
    # this plan kept the FR-291 rotation pick it already had. Tagged from the ENTRY's own origin
    # rather than from a run-level flag, because that is the field the runner stamps and the field
    # the gallery reads — one answer, not two that can disagree. A per-entry `low` fit is NOT this
    # tag: it also keeps the baseline, but it is the matcher working (`style_origin: "rotation"`
    # plus `style_wanted`), and calling a working matcher degraded would make the badge meaningless.
    if (entry.style_origin == "rotation_fallback"
            and DegradationTag.STYLE_MATCH_DEGRADED not in degradations):
        degradations.append(DegradationTag.STYLE_MATCH_DEGRADED)
    return AssetRecord(
        asset_id=entry.asset_id,
        source=entry.trend_key or (f"brief/{entry.brief_name}" if entry.brief_name else "none"),
        source_name=trend.name if trend else (entry.brief_name or ""),
        platform=entry.platform,
        creative_format=entry.creative_format,
        source_hook=_source_hook(bound, trend, entry, env),
        # FR-73 (v2.0.0) identity quartet + the FR-298 verbatim receipt:
        style_key=entry.style_key or ("brief_override" if entry.brief_influence == "override"
                                      else ""),
        brand=env.branding.brand,
        branded=entry.branded,
        # FR-337 (v2.4.0, D56): what that `style_key` MEANS on this asset — which algorithm chose
        # it, how well the matcher thought it fitted, why, and which archetype it wished the
        # registry had offered instead. Copied ACROSS untouched, never re-derived: ASSIGN owns the
        # decision (`runner._assign_visuals`), this record is its receipt, and a second opinion
        # computed here would be free to disagree with the ASSIGN console line the operator read.
        # All four stay empty on a rotation-mode run and on every override brief — no matched
        # answer applies to either, and empty is the honest way to say so.
        style_fit=entry.style_fit,
        style_reason=entry.style_reason,
        style_origin=entry.style_origin,
        style_wanted=entry.style_wanted,
        topic_key=entry.topic_key or (trend.topic_key if trend else ""),
        copy_source_post_id=prov.post_id if prov else "",
        copy_source_refs=dict(prov.refs) if prov else {},
        # FR-73 (v2.3.0, D54): which copy contract this asset shipped under. Carried straight off
        # the copy stage's own provenance rather than re-derived from `config.run` — the run-level
        # key says what the operator ASKED for, and this record has to say what this creative
        # actually got: a bound deck whose compress call failed fell back to the verbatim mapped
        # deck and is `verbatim`, and so is every image and reel in the same compress-mode run.
        copy_mode=prov.copy_mode if prov else "verbatim",
        # FR-73 (v2.1.0) — the slideshow receipt FR-309's three-part card is drawn from.
        source_post=_source_post(post_id, bound),
        source_panel_count=prov.source_panel_count if prov else 0,
        panel_map=_panel_map(prov, intel),
        ref_source=_ref_source(entry, env),
        degradations=degradations,
        brief_name=entry.brief_name,
        brief_influence_mode=entry.brief_influence,
        aspect_ratio_requested=entry.aspect_ratio,
        estimated_cost_usd=round(entry.estimated_cost_usd, 6),
        slide_count=entry.slide_count,
        # FR-298/D51 (v2.2.0): the BOUND post's own permalink, because that is the thing this
        # creative is a rendering of. The topic's `virlo_url` points at the trend page — a page
        # that lists every post in the topic — so a deck built from post 4 filed a link the
        # operator opened to find the top post's video, and the audit's "provenance points at the
        # wrong post" line is exactly that. The topic link survives only as the fallback below.
        virlo_url=_virlo_url(bound, trend, entry, env),
    )


def _bound_post(post_id: str, trend: TrendItem | None) -> Any:
    """The `SourcePost` this creative was bound to at ASSIGN (FR-304), or `None`.

    `None` on three legitimate paths and they mean the same thing to every caller: nothing was
    bound (an image, a reel, an override brief), or a topic that is no longer in `env.trends`
    cannot resolve the id (a plan resurrected from an older run). Duck-typed off the trend for the
    same reason `_source_post` is: this module reads roster objects, it does not own their type.
    """
    if not post_id:
        return None
    return next((item for item in (getattr(trend, "posts", ()) or ())
                 if str(item.post_id) == post_id), None)


def _source_hook(bound: Any, trend: TrendItem | None, entry: PlanEntry, env: Env) -> str:
    """FR-73's `source_hook` — the BOUND post's own hook, with the topic's as a labelled fallback.

    Provenance is per POST, not per topic (FR-298/§0.13): the gallery card prints this line under
    "what we were looking at", and a deck cut from post 4 that printed post 1's hook was telling
    the operator to compare our slides against a post we never touched.

    The fallback is the topic's first hook — genuinely the best available answer for an unbound
    creative, and a *different* claim from the bound one, so it is logged as such rather than
    silently substituted. `topic_p1` is the label: the topic roster's first post, which is what
    `TrendItem.hook_texts` is assembled from.
    """
    for hook in (getattr(bound, "hooks", ()) or ()):
        if str(hook).strip():
            return str(hook)
    fallback = next((hook for hook in (trend.hook_texts if trend else ()) if hook), "")
    if fallback and bound is not None:
        env.log.event("provenance_topic_fallback",
                      f"{entry.asset_id}: the bound source post carries no hook line, so meta.yaml "
                      "records the topic's first-post hook instead (labelled topic_p1)",
                      verbose_only=True, asset_id=entry.asset_id, field="source_hook",
                      source="topic_p1")
    return fallback


def _virlo_url(bound: Any, trend: TrendItem | None, entry: PlanEntry, env: Env) -> str | None:
    """FR-73's `virlo_url` — the bound post's permalink, else the topic page (labelled fallback)."""
    url = str(getattr(bound, "url", "") or "").strip()
    if url:
        return url
    fallback = trend.virlo_url if trend else None
    if fallback and bound is not None:
        env.log.event("provenance_topic_fallback",
                      f"{entry.asset_id}: the bound source post carries no permalink, so meta.yaml "
                      "records the topic page instead (labelled topic_p1)", verbose_only=True,
                      asset_id=entry.asset_id, field="virlo_url", source="topic_p1")
    return fallback


# --------------------------------------------------------------------------- the FR-73 join


def _panel_map(prov: CopyProvenance | None, intel: Any) -> list[dict[str, Any]]:
    """FR-73/FR-304/FR-306: the copy stage's rows, each joined with what that source panel SHOWED.

    The copy stage owns `{slide, source_position, source_text, ref_label, compressed}` — our
    slide's index, the source panel it renders, the words it ships, the label they were quoted
    under (empty when nothing was, including on every D54-compressed row) and whether those words
    are a compression of the source panel rather than a quote of it. This
    adds the two the slide-intelligence pass owns: `visual_brief` (the English content directive
    the slide prompt carried, FR-308) and `source_image` (the run-relative path of the downloaded
    source panel, FR-309's strip; forward-slashed and already relative to the run folder, since
    FR-75 forbids hotlinks and absolute paths alike).

    ONE row schema, always: with no intelligence at all — vision off, a failed read, a preview,
    a test — every row still gains both keys, empty and `None`. A consumer that had to ask
    whether a key exists before reading it would be reading two schemas, and the gallery's
    alignment loop is the last place that should have to branch.

    Rows keep their position and their count: a slide whose source panel was empty, unusable or
    over budget keeps its row with an empty `source_text` and an empty `ref_label`, because the
    row IS the alignment — dropping it would silently re-map slide 3's words onto slide 2, which
    is the exact defect FR-304 exists to prevent.
    """
    rows: list[dict[str, Any]] = []
    for row in (prov.panel_map if prov else ()):
        position = _int(row.get("source_position"))
        slide = intel.slide(position) if intel is not None and position else None
        # A COPY of the copy stage's row: `CopyProvenance` is the caller's data, and the meta
        # writer is not entitled to mutate it (two sibling creatives may share one provenance).
        rows.append({**dict(row),
                     "visual_brief": str(getattr(slide, "visual_brief", "") or ""),
                     "source_image": (intel.relative_image(position)
                                      if intel is not None and position else None)})
    return rows


def _source_post(post_id: str, post: Any) -> dict[str, Any] | None:
    """FR-73's nested `source_post`: whose deck this creative is a rendering OF, or `None`.

    `None` is the honest answer wherever nothing was bound — an image, a reel, an override-brief
    carousel (§0.14d), a degrade path — and the gallery falls back to its single-card layout on
    exactly that signal (FR-309).

    When a post IS bound but the topic roster can no longer resolve it (a trend dropped from
    `env.trends`, a plan resurrected from an older run), the record carries `{post_id}` ALONE:
    the id is a fact, and answering `author`/`views`/`caption` with blanks and zeros would be
    inventing provenance rather than admitting a gap. Every value that is written is a STRING or
    an int — never a `datetime` — because meta.yaml is a plain document a human reads and a
    Phase-2 publisher parses.

    `post` is `_bound_post`'s answer for this id — resolved ONCE per record, because three fields
    (`source_post`, `source_hook`, `virlo_url`) now read the same object and three independent
    lookups could disagree about which post this creative is a rendering of.
    """
    if not post_id:
        return None
    if post is None:
        return {"post_id": post_id}
    return {"post_id": post_id, "url": str(post.url or ""), "author": str(post.author or ""),
            "views": _int(post.views), "published_at": _iso(post.published_at),
            "caption": str(post.caption or "")}


def _intel_tags(intel: Any) -> list[DegradationTag]:
    """FR-306's degradations, in FR-73's enum — `vision_transcribed`, `vision_unavailable`.

    `SlideIntel.degradations` answers in the meta.yaml vocabulary by contract, so this is a
    lookup rather than a mapping table: one spelling, owned by `DegradationTag`. A value the enum
    does not know is skipped rather than crashing the creative's meta — an unknown tag is a
    version skew between two modules, and the render is already paid for.
    """
    tags: list[DegradationTag] = []
    for value in (getattr(intel, "degradations", ()) or ()):
        try:
            tags.append(DegradationTag(str(value)))
        except ValueError:
            continue
    return tags


def _iso(value: Any) -> str | None:
    """An ISO 8601 string, or `None` — FR-73 stores strings, never `datetime` objects.

    Re-derived here rather than imported from `sources.slide_intel` (which keeps the identical
    discipline for `source.yaml`): `generate` imports nothing from `sources`, and a four-line
    formatter is not worth inverting that direction for.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value or "").strip()
    return text or None


def _int(value: Any) -> int:
    """A source-controlled number as an int; anything unreadable is 0, never an exception."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------- small helpers


def _ref_source(entry: PlanEntry, env: Env) -> str:
    """FR-73's honest provenance: what this job's uploaded references actually came FROM.

    Post-D46 the vocabulary is `"brief" | ""`. `"style"` is dead with the channel it named (F3):
    a meta-style is text-only DNA now, ships no picture to any render job, and a field still
    claiming "style" would be the one place in the run that says the look was copied from images
    the renderer never saw.

    `"brief"` is claimed only when the brief actually SHIPS photos — a brief with directives and
    no images contributes no reference, and naming one would make this field a second, wrong
    answer to "why does this look like this". The anchor slide and the seed frame are excluded on
    purpose: they are our own generated artifacts, chained inside one creative and already
    enumerated as assets (FR-72), not a provenance an operator can go and look at.
    """
    brief = env.campaign_briefs.get(entry.brief_name or "")
    return "brief" if brief is not None and brief.reference_image_paths else ""


def _abandon(entry: PlanEntry, env: Env, folder: AssetFolder) -> AssetRecord:
    """FR-108/201/203: terminal folder, `abandoned` status, one ledger line naming the taskId.

    The job itself is neither cancelled at Kie nor resubmitted — it was billed at submission and
    may still complete unclaimed. Saying so, with the id, is the whole point of the ledger.

    It is also the whole point of `_Tally`: this path holds no outcome (it runs inside the
    `CancelledError` the grace window raises), so without the running receipt an abandoned creative
    filed `$0`, no job ids and no timestamps against work that was really submitted and really
    billed. The tally supplies all four — every terminal job plus the estimate still held against
    the one that never came back — and the open job's id is appended here, since it has no terminal
    line to have added itself with.
    """
    task_id = _OPEN_TASKS.pop(entry.asset_id, None)
    tally = _TALLIES.pop(entry.asset_id, None) or _Tally()
    if task_id and task_id not in tally.job_ids:
        tally.job_ids.append(task_id)  # the job still running: billed, unclaimed, named (FR-203)
    reason = (f"abandoned after the {GRACE_S:.0f}s grace window (job {task_id or 'unknown'}) — "
              "it was billed at submission and may still complete unclaimed at Kie (FR-108/203)")
    entry.status = PlanEntryStatus.ABANDONED
    entry.skip_reason = entry.skip_reason or reason
    env.ledger.terminal(entry.asset_id, "", task_id, "abandoned")
    # FR-73: `event_id` points at the line that explains this asset — never null on a terminal.
    event_id = env.log.warn("abandoned", f"{entry.asset_id}: {reason}", asset_id=entry.asset_id,
                            task_id=task_id or "")
    if env.say is not None:  # §1.10: the abandoned line carries FR-108's grace sentence
        ordinal = entry.asset_id.rsplit("_", 1)[-1]
        env.say(f"          abandoned {ordinal:>2} {entry.creative_format:<8} "
                f"job {task_id or 'unknown'} — billed at submission, may still complete unclaimed")
    return folder.skip(reason, DegradationTag.ABANDONED, event_id=event_id,
                       native_size_rendered=entry.aspect_ratio, **tally.meta())


def _unspent(entry: PlanEntry, env: Env, event: str, reason: str) -> dict[str, Any]:
    """The terminal block for a creative that never reached the money door — $0, and an event id.

    Deliberately small: the honest answer for a creative nothing was ordered for is that it cost
    nothing, came back at no size (so the REQUESTED ratio stands, never an empty string the gallery
    would print as `ratio 1:1 → `), and is explained by exactly one log line.
    """
    return {"actual_cost_usd": 0.0,
            "native_size_rendered": entry.aspect_ratio,
            "event_id": env.log.warn(event, f"{entry.asset_id}: {reason}",
                                     asset_id=entry.asset_id,
                                     creative_format=entry.creative_format)}


def _fail(entry: PlanEntry, env: Env, folder: AssetFolder, reason: str,
          tag: DegradationTag | None = None, *, cost: float = 0.0,
          outcome: RenderOutcome | None = None, referenced: bool = False,
          delivered: Path | None = None,
          vision: VisionCheckResult = VisionCheckResult.NOT_CHECKED) -> AssetRecord:
    """Terminal failure that keeps its paid artifacts (FR-74) and stays in the plan (FR-4).

    Records the SAME block a delivered creative records, minus what genuinely does not exist yet —
    the audit's finding was that a failed image filed a cost and a job id and nothing else, so two
    creatives with identical folders on disk answered "which model made this" and "what size did it
    come back at" differently purely because one of them failed (`carousel.package()` has written
    the full block since v2.1.4; this is the standalone image path catching up):

    * `model_ids` name the route this job ACTUALLY took (FR-241/FR-270) — `image_edit` when it
      carried references, `image` when it did not — and are written only when a job was really
      submitted, because a creative that died at prompt assembly used no model at all.
    * `native_size_rendered` is measured off the delivered file when there IS one (a store failure,
      a full disk, a failed check all happen with real bytes on disk) and otherwise falls back to
      the requested ratio, which is `carousel._native_size`'s rule: the field is never empty,
      because the gallery prints it as the right-hand side of `ratio 1:1 → …`.
    * `vision_check_result` is passed through rather than defaulted, so a creative that failed
      AFTER its check still says what the check said.
    """
    if entry.status is PlanEntryStatus.PENDING:
        entry.status = PlanEntryStatus.FAILED
    entry.skip_reason = entry.skip_reason or reason
    extra: dict[str, Any] = {  # FR-73: the run-log line this meta.yaml points back at
        "actual_cost_usd": round(cost, 6),
        "native_size_rendered": (
            native_size(delivered, entry.aspect_ratio, log=env.log, asset_id=entry.asset_id)
            if delivered is not None else entry.aspect_ratio),
        "vision_check_result": vision,
        "event_id": env.log.error("creative_failed", f"{entry.asset_id}: {reason}",
                                  asset_id=entry.asset_id, cost_usd=round(cost, 6)),
    }
    # A runway refusal (D51) is the one "outcome" that describes a job which never existed: it has
    # no taskId, no timestamps and no model, so it writes none of them rather than claiming a route
    # nothing took.
    if outcome is not None and outcome.fail_cause is not RenderFailCause.NO_RUNWAY:
        extra["model_ids"] = [env.config.models.image_edit if referenced
                              else env.config.models.image, env.config.models.image_profile]
        extra["kie_job_ids"] = [outcome.task_id] if outcome.task_id else []
        extra["job_submission_timestamp"] = outcome.submitted_at
        extra["job_completion_timestamp"] = outcome.completed_at
    return folder.skip(reason, tag, **extra)


__all__ = ["Env", "GRACE_S", "Report", "ROLE_IMAGE", "create", "ledger_hooks"]
