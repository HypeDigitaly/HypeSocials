"""One job's reference set: what is attached, and what each attachment is FOR (FR-18/191/200).

Purpose: hand a render job the campaign brief's own product photos when it ships any
(FR-144/145), uploaded once per run (FR-200), and give every attachment its FR-191 role line. All
three format modules attach through this one function, so a brief's product photo is never
introduced as "layout, palette and treatment only" — the wording that makes a product vanish from
its own ad. The same module answers the three style/branding questions a format module asks while
assembling a prompt (`style_of`, `branding_block`, `wordmark`), because they travel with the same
entry and the same registry.

**Text-to-image is the default route (D46/FR-18, v2.1.0).** A meta-style ships NO pixels: its
textual DNA qualifies the render (FR-17), so most jobs attach nothing at all and that is the
NORMAL case, not a degradation. The only images a job may carry are (a) a brief's own photos,
attached here, and (b) chained artifacts a format module makes itself and passes in beside these —
the carousel anchor slide (FR-95) and the reel's seed frame (FR-24).

Public API: `await attach(entry, env, folder)` · `role_lines(refs)` · `provenance(refs)` ·
`style_of(entry, env)` · `branding_block(entry, env, style)` · `wordmark(entry, env)` ·
`reset_uploads()` · `Reference` · `UploadMemo`.

Invariants:
- **Only `brief`-kinded local files are attached.** `env.local_refs` is the runner's brief-photo
  channel and nothing else; any other kind is a stale caller, and it is dropped with a logged line
  rather than silently uploaded as a look the style never asked for.
- **One upload per file per run** (FR-200/244). Kie keeps an upload ~24 h, so the memo is created
  per run and thrown away with it — a URL memoized across runs is a reference that silently 404s
  mid-batch. Within one run it is what makes a brief's photo upload once, not once per creative.
- **An `override` brief suppresses the style entirely** (FR-144/M14): no `render_prompt` — the
  brief's own directives and its own photos are the whole creative. Its photos still attach.
- **A failed upload drops one reference, never the job** (FR-200, 20 §10's FR-244 row); nothing
  here raises. `reference_free` is marked only when references were EXPECTED AND LOST — a brief
  shipped photos and not one of them could be attached (FR-18's "an input, not a prerequisite").
  A style-driven creative that attaches nothing is silent, because it has lost nothing.

Do not: select which topic a creative quotes (`copywrite` owns that), price anything, write the
branding block's words (`prompts_engine` owns the wording — §1.4 module split; this module only
decides WHICH creative gets one), or upload anything out of the run's `source/` folder (D46's
carve-out boundary: no Virlo byte or URL may reach a render payload).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hypesocials import prompts_engine, render, styles
from hypesocials.models import DegradationTag, MetaStyle, PlanEntry

if TYPE_CHECKING:  # runtime import would be circular: `generate/__init__.py` imports this module
    from hypesocials.generate import Env

logger = logging.getLogger(__name__)

#: Local file path -> the Kie URL it was uploaded to, built ONCE per run and thrown away with the
#: run (FR-200/FR-244). Run-scoped on purpose: Kie's file host keeps an upload roughly 24 h, so a
#: URL memoized across runs is a reference that silently 404s mid-batch. The type lives HERE, with
#: the only code that fills it, since D46 left this module the sole uploader of local files.
UploadMemo = dict[Path, str]

#: FR-191's brief wording — the one role line this module writes. The style role sentence retired
#: with the channel it introduced (D46/FR-18): a house style contributes prose to the prompt now,
#: never a picture to introduce.
BRIEF_ROLE = ("brief subject — this product/object IS the subject; reproduce it faithfully; "
              "contribute style only where it does not alter the subject; no added text or logo")

#: run directory -> that run's `UploadMemo`. Run-scoped by construction: every run gets its own
#: timestamped `run_dir`, so no URL can survive into a later run, which is the whole point of the
#: 24 h retention rule (FR-200/244). `reset_uploads()` clears it for a process that outlives a run
#: (tests, and any future long-lived host).
_MEMOS: dict[str, UploadMemo] = {}


@dataclass(frozen=True, slots=True)
class Reference:
    """One attachment: the URL the job sends, the FR-191 line introducing it, its provenance.

    `kind` is the provenance as a word rather than something a reader has to infer from the role
    sentence. Post-D46 the vocabulary is two words: `brief` (a photo the operator's campaign brief
    shipped, the only kind `attach()` ever produces) and `chained` (an artifact this run generated
    and passed back in — the carousel anchor slide, the reel seed frame). NFR-5 wants a creative's
    provenance reconstructable from the logs alone, and "which of these pictures was the operator's
    own product photo" is exactly the question a role sentence answers only by string-matching.

    `chained` is the DEFAULT because the format modules construct those references positionally
    (`Reference(anchor_url, ROLE)`), and it keeps their FR-191 punctuation unchanged.
    """

    url: str
    role: str = ""
    kind: str = "chained"


def role_lines(refs: Sequence[Reference]) -> list[str]:
    """FR-191's `reference_roles` block — one line per attachment, in attachment order.

    A brief photo reads `Image 2: …` and a chained artifact reads `Image 1 — …`; the punctuation
    difference is quoted from §1.9 F19, not invented, and it makes the two provenances scannable in
    a logged prompt. The anchor's own line is re-rendered from `carousel_anchor_instruction.md`
    over the top of this one (FR-190) — this is its floor, never its final wording.
    """
    return [f"Image {index}: {ref.role}" if ref.kind == "brief" else f"Image {index} — {ref.role}"
            for index, ref in enumerate(refs, start=1)]


def provenance(refs: Sequence[Reference]) -> dict[str, int]:
    """How many attachments came from each source, always both keys (FR-155/NFR-5).

    Both, including the zeros: "0 brief" is the answer to "did this creative's brief photos reach
    the job", and an absent key is not. Post-D46 there is no `style` count to keep — FR-155's
    amended `kie_job_submitted` shape drops style-reference entries outright and calls a
    reference_count of 0 the normal case for a text-only render.
    """
    counts = {"brief": 0, "chained": 0}
    for ref in refs:
        counts[ref.kind] = counts.get(ref.kind, 0) + 1
    return counts


def style_of(entry: PlanEntry, env: Env) -> MetaStyle | None:
    """The meta-style this creative wears, or `None` when it wears none (FR-290/291).

    `None` in exactly three cases, and every caller wants the same answer in all three: no registry
    is wired (previews, tests), the entry runs under an `influence: override` brief — FR-144's
    "suppresses the assigned style entirely", prompt AND pictures, M14 — or its `style_key` no
    longer resolves against the registry, which is logged and degraded rather than raised, because
    a stale key must cost a look, not a creative.
    """
    registry = getattr(env, "styles", None)
    if registry is None or not entry.style_key or _overridden(entry, env):
        return None
    try:
        return styles.style_for(registry, entry.style_key)
    except styles.StyleRegistryError as exc:
        env.log.warn("style_unknown",
                     f"{entry.asset_id}: {exc}; this creative renders without a house style",
                     asset_id=entry.asset_id, style_key=entry.style_key)
        return None


def branding_block(entry: PlanEntry, env: Env, style: MetaStyle | None = None) -> str:
    """FR-292's second channel for THIS creative — accent colours, letterforms, placement, the
    profile's `never:` lines — or `""` when the creative carries no signature.

    §1.4's module split puts the WORDING in `prompts_engine` (which owns rendering and its
    no-filesystem contract) and the DECISION here: `entry.branded` is the deterministic rotation
    `styles.assign_branding` already wrote, and the format modules are the only callers that know
    which prompt is being assembled. The wordmark itself is never in this block — it is a
    TEXT-block entry (B1/M13), which is why a reel's director role can refuse this block and
    still keep the seed frame's signature continuous.

    Direct call — the by-name seam this function shipped with mid-wave was collapsed at the W2
    conductor wire-in once `prompts_engine.branding_block` landed public with the pinned arity
    (contracts W2 addendum item 2). `None` branding renders `""` on the engine side.
    """
    if not getattr(entry, "branded", False):
        return ""
    return prompts_engine.branding_block(getattr(env, "branding", None), style)


def wordmark(entry: PlanEntry, env: Env) -> str:
    """The brand name THIS creative signs itself with, or `""` when it carries no signature.

    B1's channel, decided here and rendered nowhere else: the wordmark is a TEXT-block entry, so it
    travels as a `build_context(wordmark=…)` string that `_onimage_text` quotes verbatim — branded
    is simply "this string is non-empty". It is never part of `{{branding_block}}`, because every
    render scaffold declares the TEXT block the ONLY source of renderable words and a brand name
    spelled anywhere else is a description the model is told to ignore.

    Empty for an unbranded entry, and empty rather than raising when the run carries no branding
    config at all (previews, tests): an unsigned frame is a valid frame, a crash is not.
    """
    if not getattr(entry, "branded", False):
        return ""
    branding = getattr(env, "branding", None)
    profile = getattr(branding, "profiles", {}).get(getattr(branding, "brand", ""))
    return getattr(profile, "wordmark", "") or ""


def reset_uploads() -> None:
    """Forget every run's upload memo — for tests and for any process that outlives one run."""
    _MEMOS.clear()


async def attach(entry: PlanEntry, env: Env, folder: Any) -> list[Reference]:
    """This job's finished reference set: uploaded, capped and role-labelled. Never raises.

    Post-D46 that set is the campaign brief's own photos and nothing else — an ordinary
    style-driven creative attaches zero references and says nothing about it, because text-to-image
    is the route the style was written for (FR-17/18). The one thing worth a word is a LOSS: a
    brief shipped photos and not one of them survived the upload.
    """
    style = style_of(entry, env)
    # The name this creative's look answers to in the log — M14's `brief_override` when a brief
    # took the style's place, so the line and the meta.yaml field say the same word.
    label = style.key if style is not None else (
        "brief_override" if _overridden(entry, env) else entry.style_key or "")
    memo = _MEMOS.setdefault(str(getattr(env, "run_dir", "")), {})
    wanted = _wanted(entry, env)
    refs: list[Reference] = []
    for path in wanted:
        url = await _upload(path, memo, entry, env)
        if url:
            refs.append(Reference(url, BRIEF_ROLE, kind="brief"))
    if wanted and not refs:
        # FR-18: brief images are an input, not a prerequisite — the job proceeds on the style's
        # written guidance alone. But this creative EXPECTED pictures and lost every one of them
        # (missing on disk, or the upload failed), so the absence is marked AND logged, in metadata
        # and in the gallery. A creative that expected none never reaches this branch.
        folder.mark(DegradationTag.REFERENCE_FREE)
        env.log.warn("reference_free",
                     f"{entry.asset_id}: none of the {len(wanted)} brief reference image(s) could "
                     "be attached; the job renders on the style's written guidance and FR-96's "
                     "content sentence alone (FR-18)",
                     asset_id=entry.asset_id, style_key=label)
    elif refs:
        # FR-155/NFR-5: the trim that happens here — a brief's photos hitting the profile's own
        # ceiling — was the last silent one on this path.
        counts = provenance(refs)
        env.log.event("reference_set",
                      f"{entry.asset_id}: {len(refs)} reference(s) — {counts['brief']} brief",
                      asset_id=entry.asset_id, style_key=label,
                      reference_count=len(refs), reference_sources=counts)
    return refs


def _wanted(entry: PlanEntry, env: Env) -> list[Path]:
    """The local files this job wants attached, de-duplicated and capped (FR-272).

    One channel only: the `brief`-kinded entries the runner pre-resolved into `env.local_refs`
    (FR-144/145). The style channel is gone with the pictures it carried (D46/FR-18), so there is
    no ordering rule left to enforce — a brief's photos are the whole list, in the brief's own
    order. Capped BEFORE the uploads rather than after, because an upload the job will not attach
    is a second of somebody's run spent on nothing.

    Any other kind is DROPPED with a logged line. Post-pivot `runner._local_refs` emits `"brief"`
    and nothing else, so a stray kind means a stale caller, and uploading it would attach a picture
    no requirement asked for to a job the operator is paying for.
    """
    local = list(getattr(env, "local_refs", {}).get(entry.asset_id, ()))
    wanted: list[Path] = []
    seen: set[Path] = set()
    for raw, kind in local:
        if kind != "brief":
            env.log.warn("reference_kind_unknown",
                         f"{entry.asset_id}: reference {Path(raw).name} arrived as kind {kind!r}; "
                         "only brief photos are attached post-D46 (FR-18) — dropped",
                         asset_id=entry.asset_id, reference=Path(raw).name)
            continue
        if (path := Path(raw)) not in seen:
            seen.add(path)
            wanted.append(path)
    return wanted[:_ceiling(env)]


async def _upload(path: Path, memo: UploadMemo, entry: PlanEntry, env: Env) -> str:
    """This file's Kie URL, uploaded at most once per run (FR-200). `""` when the upload failed.

    Only successes are memoized: a file that failed once may be a transient upload error, and one
    retry per job is cheaper than teaching the memo to remember failures for a whole run.
    """
    if (url := memo.get(path)):
        return url
    try:
        memo[path] = url = await render.upload_file(path)
    except Exception as exc:  # noqa: BLE001 — a failed upload is one fewer reference, never a job
        env.log.warn("reference_upload_failed",
                     f"{entry.asset_id}: {path.name} could not be uploaded ({exc}); the job "
                     "proceeds with its remaining references (FR-200)",
                     asset_id=entry.asset_id, reference=path.name)
        return ""
    return url


def _overridden(entry: PlanEntry, env: Env) -> bool:
    """FR-144/M14: is this creative's style suppressed by an `override` brief?

    Same predicate `build_context` applies to `render_prompt` — override AND actual visual
    directives — so a brief can never replace the pictures while leaving the style's prompt in
    force, or the other way round.
    """
    brief = getattr(env, "campaign_briefs", {}).get(entry.brief_name or "")
    mode = entry.brief_influence or (brief.influence if brief else "")
    return bool(brief and mode == "override" and brief.visual_directives)


def _ceiling(env: Env) -> int:
    """The provider's hard reference ceiling for this run's image profile (FR-272).

    The only cap left: the retired `styles.refs_per_job` key sized a style window that no longer
    exists (FR-17/18 tombstone both), and a brief ships the photos it ships — trimming those to a
    house-style budget would drop the operator's own product from its own ad.
    """
    return render.get_profile(env.config.models.image_profile).limits.max_image_urls or 16


__all__ = ["BRIEF_ROLE", "Reference", "UploadMemo", "attach", "branding_block", "provenance",
           "reset_uploads", "role_lines", "style_of", "wordmark"]
