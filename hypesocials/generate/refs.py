"""One job's reference set: what is attached, and what each attachment is FOR (FR-18/91/191/200).

Purpose: merge the trend's coherent group with this run's local files — a campaign brief's own
product photos (FR-144/145) and the Inspiration pick (D13) — upload whatever is local (FR-200),
cap the MERGED set at what both the profile and `reference_images_per_job` allow (FR-91), and give
every attachment its FR-191 role line. All three format modules attach through this one function,
so a brief's product photo is never introduced as "layout, palette and treatment only" — the
wording that makes a product vanish from its own ad.

Public API: `await attach(entry, env, folder)` · `role_lines(refs)` · `Reference`.

Invariants: provenance decides the wording (`env.local_refs` carries `(path, kind)`; a trend or
inspiration picture is a LOOK, a brief's picture is the SUBJECT) · a failed upload drops one
reference, never the job (FR-200, 20 §10's FR-244 row) · absence is marked AND logged, never
silent (FR-18) · a brief's own images always fit, the trend slice yields room first.

Do not: select references (`sources/` owns FR-91 selection), price anything, or raise.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hypesocials import render
from hypesocials.models import DegradationTag, PlanEntry

if TYPE_CHECKING:  # runtime import would be circular: `generate/__init__.py` imports this module
    from hypesocials.generate import Env

#: FR-191's three wordings, one per provenance.
TREND_ROLE = ("trend reference — layout, palette, typography and treatment only; no words, "
              "no logo, no chrome, no person's identity")
INSPIRATION_ROLE = ("inspiration reference — layout, palette, typography and treatment only; "
                    "no words, no logo, no person's identity")
BRIEF_ROLE = ("brief subject — this product/object IS the subject; reproduce it faithfully; "
              "contribute style only where it does not alter the subject; no added text or logo")
_ROLES = {"trend": TREND_ROLE, "inspiration": INSPIRATION_ROLE, "brief": BRIEF_ROLE}


@dataclass(frozen=True, slots=True)
class Reference:
    """One attachment: the URL the job sends, and the FR-191 line that introduces it."""

    url: str
    role: str = TREND_ROLE


def role_lines(refs: Sequence[Reference]) -> list[str]:
    """FR-191's `reference_roles` block — one line per attachment, in attachment order."""
    return [f"Image {index}: {ref.role}" for index, ref in enumerate(refs, start=1)]


async def attach(entry: PlanEntry, env: Env, folder: Any) -> list[Reference]:
    """This job's finished reference set: uploaded, capped and role-labelled. Never raises."""
    local: list[Reference] = []
    for path, kind in getattr(env, "local_refs", {}).get(entry.asset_id, ()):
        try:
            local.append(Reference(await render.upload_file(path), _ROLES.get(kind, TREND_ROLE)))
        except Exception as exc:  # noqa: BLE001 — any upload failure is one fewer reference
            env.log.warn("reference_upload_failed",
                         f"{entry.asset_id}: {Path(path).name} could not be uploaded ({exc}); the "
                         "job proceeds with its remaining references (FR-200)",
                         asset_id=entry.asset_id, reference=Path(path).name)
    cap = _cap(env)
    trend = env.trends.get(entry.trend_key or "")
    group = list(trend.reference_groups[0]) if trend and trend.reference_groups else []
    # A brief's own pictures are what the creative is ABOUT, so the trend slice yields room for
    # them rather than pushing them past the cap (FR-91 counts the merged set, not each source).
    refs = [*(Reference(url) for url in group[:max(0, cap - len(local))]), *local][:cap]
    if not refs:  # FR-18: metadata, log AND gallery — absence is visible, never silent
        folder.mark(DegradationTag.REFERENCE_FREE)
        env.log.warn("reference_free",
                     f"{entry.asset_id}: no reference image could be attached; the job renders on "
                     "FR-96's deterministic content sentence alone (FR-18)",
                     asset_id=entry.asset_id)
    return refs


def _cap(env: Env) -> int:
    """FR-91's set size: the operator's `reference_images_per_job`, never past the profile's own."""
    limit = render.get_profile(env.config.models.image_profile).limits.max_image_urls or 16
    return max(1, min(limit, env.config.sources.reference_images_per_job or limit))


__all__ = ["BRIEF_ROLE", "INSPIRATION_ROLE", "Reference", "TREND_ROLE", "attach", "role_lines"]
