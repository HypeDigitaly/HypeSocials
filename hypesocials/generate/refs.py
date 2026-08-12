"""One job's reference set: what is attached, and what each attachment is FOR (FR-18/191/200).

Purpose: hand a render job the pictures that PROVE its assigned house style — the meta-style's own
reference-window slice (FR-290/291), uploaded once per run (FR-200) — merged with a campaign
brief's own product photos when it ships any (FR-144/145), and give every attachment its FR-191
role line. All three format modules attach through this one function, so a brief's product photo is
never introduced as "layout, palette and treatment only" — the wording that makes a product vanish
from its own ad.

Public API: `await attach(entry, env, folder)` · `role_lines(refs)` · `provenance(refs)` ·
`style_of(entry, env)` · `branding_block(entry, env, style)` · `wordmark(entry, env)` ·
`reset_uploads()` · `Reference`.

Invariants:
- **Style images come FIRST, brief images after** (F19). Every render scaffold tells the model to
  follow the first reference listed, so ordering IS precedence: the house style wins the look and
  the brief keeps its subject.
- **One upload per file per run** (FR-200/244). Kie keeps an upload ~24 h, so the memo is created
  per run and thrown away with it — a URL memoized across runs is a reference that silently 404s
  mid-batch. Within one run it is what makes a style's five brand cards upload once, not once
  per job.
- **An `override` brief suppresses the style entirely** (FR-144/M14): no `render_prompt`, no style
  pictures — the brief's own directives and its own photos are the whole creative.
- **A failed upload drops one reference, never the job** (FR-200, 20 §10's FR-244 row); absence is
  marked AND logged, never silent (FR-18); nothing here raises.

Do not: select which topic a creative quotes (`copywrite` owns that), price anything, write the
branding block's words (`prompts_engine` owns the wording — §1.4 module split; this module only
decides WHICH creative gets one), or validate reference bytes (`styles.pick_reference_window`
already dropped the unusable ones).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hypesocials import prompts_engine, render, styles
from hypesocials.models import DegradationTag, MetaStyle, PlanEntry
from hypesocials.styles import UploadMemo

if TYPE_CHECKING:  # runtime import would be circular: `generate/__init__.py` imports this module
    from hypesocials.generate import Env

logger = logging.getLogger(__name__)

#: FR-191's two wordings, one per provenance. The style line is quoted verbatim from §1.9 F19 —
#: including its em dash, which is why `role_lines` punctuates the two kinds differently.
BRIEF_ROLE = ("brief subject — this product/object IS the subject; reproduce it faithfully; "
              "contribute style only where it does not alter the subject; no added text or logo")
STYLE_ROLE = ("house style reference{label}: layout, palette, typography and treatment only; "
              "no words, no logos.")

#: run directory -> that run's `UploadMemo`. Run-scoped by construction: every run gets its own
#: timestamped `run_dir`, so no URL can survive into a later run, which is the whole point of the
#: 24 h retention rule (FR-200/244). `reset_uploads()` clears it for a process that outlives a run
#: (tests, and any future long-lived host).
_MEMOS: dict[str, UploadMemo] = {}


@dataclass(frozen=True, slots=True)
class Reference:
    """One attachment: the URL the job sends, the FR-191 line introducing it, its provenance.

    `kind` is the provenance as a word (`style` / `brief`) rather than something a reader has to
    infer from the role sentence. NFR-5 wants a creative's provenance reconstructable from the logs
    alone, and "which of these pictures was the operator's own product photo" is exactly the
    question a role sentence answers only by string-matching.
    """

    url: str
    role: str = ""
    kind: str = "style"


def role_lines(refs: Sequence[Reference]) -> list[str]:
    """FR-191's `reference_roles` block — one line per attachment, in attachment order.

    The style line follows §1.9 F19 verbatim (`Image 1 — house style reference "…": …`) and the
    brief line keeps its existing `Image 2: …` shape; the punctuation difference is quoted, not
    invented, and it also makes the two provenances scannable in a logged prompt.
    """
    return [f"Image {index} — {ref.role}" if ref.kind == "style" else f"Image {index}: {ref.role}"
            for index, ref in enumerate(refs, start=1)]


def provenance(refs: Sequence[Reference]) -> dict[str, int]:
    """How many attachments came from each source, always both keys (FR-155/NFR-5).

    Both, including the zeros: "0 style" is the answer to "did this creative's house style reach
    the job", and an absent key is not. The counts are what the funnel's `render` row forecasts and
    what `kie_job_submitted` records per job, so the forecast and the fact stay comparable after
    the run rather than only in aggregate.
    """
    counts = {"style": 0, "brief": 0}
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
    """This job's finished reference set: uploaded, capped and role-labelled. Never raises."""
    style = style_of(entry, env)
    # The name this creative's look answers to in the log — M14's `brief_override` when a brief
    # took the style's place, so the line and the meta.yaml field say the same word.
    label = style.key if style is not None else (
        "brief_override" if _overridden(entry, env) else entry.style_key or "")
    memo = _MEMOS.setdefault(str(getattr(env, "run_dir", "")), {})
    refs: list[Reference] = []
    for path, kind in _wanted(entry, env, style):
        url = await _upload(path, memo, entry, env)
        if url:
            refs.append(Reference(url, _style_role(label) if kind == "style" else BRIEF_ROLE,
                                  kind=kind))
    counts = provenance(refs)
    if style is not None and style.reference_images and not counts["style"]:
        # The style declared pictures and none of them made it — missing on disk, not an image, or
        # the upload failed. A text-only style is a legitimate degrade (its written guidance is
        # intact, FR-18), but the operator hears which creative lost its proof (FR-295's warning
        # says which FILE, once, at pre-flight; this says which CREATIVE, here).
        folder.mark(DegradationTag.STYLE_REFS_MISSING)
        env.log.warn("style_refs_missing",
                     f"{entry.asset_id}: no reference image of style {label!r} could be attached; "
                     "the creative renders on the style's written guidance alone (FR-18/295)",
                     asset_id=entry.asset_id, style_key=label)
    if not refs:  # FR-18: metadata, log AND gallery — absence is visible, never silent
        folder.mark(DegradationTag.REFERENCE_FREE)
        env.log.warn("reference_free",
                     f"{entry.asset_id}: no reference image could be attached; the job renders on "
                     "the style's written guidance and FR-96's content sentence alone (FR-18)",
                     asset_id=entry.asset_id, style_key=label)
    else:
        # FR-155/NFR-5: the trim that happens here — the merged set hitting the profile's ceiling,
        # a brief's photos arriving behind the style window — was the last silent one on this path.
        env.log.event("reference_set",
                      f"{entry.asset_id}: {len(refs)} reference(s) — {counts['style']} style, "
                      f"{counts['brief']} brief",
                      asset_id=entry.asset_id, style_key=label,
                      reference_count=len(refs), reference_sources=counts,
                      reference_window=entry.trend_reuse_index)
    return refs


def _wanted(entry: PlanEntry, env: Env, style: MetaStyle | None) -> list[tuple[Path, str]]:
    """The local files this job wants attached, in F19 order, already capped (FR-272).

    Style first, brief after: the render scaffolds tell the model to follow the first reference
    listed, so this order IS the FR-145 precedence — the house style wins the look, the brief keeps
    its subject. Capped BEFORE the uploads rather than after, because an upload the job will not
    attach is a second of somebody's run spent on nothing.

    Two channels feed the style half: the assigned style's own rotated window (`styles`, the
    authority) and any `style`-kinded entry the run pre-resolved into `env.local_refs`. Paths are
    de-duplicated, so a run that fills both channels attaches — and uploads — each file once. A
    kind this vocabulary does not know is treated as a style reference: the pre-pivot `inspiration`
    pool WAS a folder of house-style pictures, and it retires with W3.5 rather than vanishing here.
    """
    local = list(getattr(env, "local_refs", {}).get(entry.asset_id, ()))
    wanted: list[tuple[Path, str]] = []
    if style is not None:
        wanted += [(path, "style")
                   for path in styles.pick_reference_window(style, entry.trend_reuse_index,
                                                            _cap(env))]
    if not _overridden(entry, env):  # M14: an override brief attaches no style picture at all
        wanted += [(Path(path), "style") for path, kind in local if kind != "brief"]
    wanted += [(Path(path), "brief") for path, kind in local if kind == "brief"]
    unique: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for path, kind in wanted:
        if path not in seen:
            seen.add(path)
            unique.append((path, kind))
    return unique[:_ceiling(env)]


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


def _style_role(key: str) -> str:
    """§1.9 F19's role sentence, naming the style when there is a name to give."""
    return STYLE_ROLE.format(label=f' "{key}"' if key else "")


def _cap(env: Env) -> int:
    """The style window's width: `styles.refs_per_job`, never past the profile's own ceiling."""
    return max(1, min(_ceiling(env), env.config.styles.refs_per_job or _ceiling(env)))


def _ceiling(env: Env) -> int:
    """The provider's hard reference ceiling for this run's image profile (FR-272)."""
    return render.get_profile(env.config.models.image_profile).limits.max_image_urls or 16


__all__ = ["BRIEF_ROLE", "Reference", "STYLE_ROLE", "attach", "branding_block", "provenance",
           "reset_uploads", "role_lines", "style_of", "wordmark"]
