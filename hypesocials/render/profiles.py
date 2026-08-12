"""Declarative render-model profiles — the only place a provider's parameter names live.

Purpose: turn the engine's standard render inputs (`RenderParams` + `RenderRefs`) into one
provider request — route id plus `input` object — and declare each family's reference limits and
prompt template set (FR-272). Pure data and pure functions: no I/O, no config, no logging. Field
shapes are copied verbatim from the live requests in `spikes/RESULTS.md` §B and §C.
Public API: `get(name)` · `RenderProfile` · `ReferenceLimits` · `UnknownProfileError` ·
`PROFILE_NAMES`.
Invariants:
- One profile carries BOTH GPT Image 2 routes (FR-241) — reference-bearing to image-to-image with
  `input_urls`, reference-free to text-to-image. No route name is spoken outside this file.
- Every list is capped at the model's documented limit before it is sent: a rejected job is a
  paid round trip avoidable by counting.
- Ratio/resolution pairs Kie refuses at *task creation* are clamped here, not discovered at
  submission (20 §8c, RESULTS.md §B).
- An unknown profile raises at lookup; the exit-2 refusal wording is pre-flight's job (FR-272).
Do not: put a config default here, call a provider, or set a parameter the engine has no reason
to set — everything else stays at provider default (FR-240, 20 §8a).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from hypesocials.models import RenderParams, RenderRefs

#: Profile names; also the `prompts/<profile>/` template-set names (FR-181/262, models.py).
GPT_IMAGE_2 = "gpt-image-2"
SEEDANCE_2_5 = "seedance-2-5"

# Kie route ids. These are the profile's DECLARATION of the family's routes (FR-272), and the
# reference-bearing one is overridden by `models.image` / `models.video` from config (FR-270) —
# the reference-free sibling has no config key of its own (30 §2 ships one image model key).
_GPT_IMAGE_2_REF_ROUTE = "gpt-image-2-image-to-image"
_GPT_IMAGE_2_TEXT_ROUTE = "gpt-image-2-text-to-image"
_SEEDANCE_ROUTE = "bytedance/seedance-2-5"

_IMAGE_RESOLUTIONS = ("1K", "2K", "4K")
#: 1K-only ratios, plus `auto`/unset which renders 1K whatever else is asked for (20 §8c).
_ONE_K_ONLY_RATIOS = frozenset({"", "auto", "5:4", "4:5", "3:1", "1:3", "9:21"})
#: FR-192's production ceiling, enforced where the parameter is built rather than trusted from
#: config: above 2K the model is documented unstable, and 1:1 at 4K fails task creation outright.
_IMAGE_RESOLUTION_CEILING = "2K"

#: 50 §7 states the truncation ORDER but no number, and no provider documents a prompt-length
#: limit. 10 000 characters is therefore this ENGINE's bound, not a provider fact: generous for
#: every shipped template, tight enough that a runaway style brief cannot buy a rejected job.
MAX_PROMPT_CHARS = 10_000

SEEDANCE_DURATION_RANGE = (4, 30)  # FR-164; the provider's `-1` auto value is never sent
_SEEDANCE_DEFAULT_DURATION_S = 5


class UnknownProfileError(LookupError):
    """No profile is declared for this name — pre-flight turns this into the exit-2 refusal."""


@dataclass(frozen=True, slots=True)
class ReferenceLimits:
    """What one model family will actually accept as reference media.

    Declared so callers cap *before* spending (FR-272). `video_pixel_window` is kept as the
    profile's own documented bound (spikes/RESULTS.md §C) even though nothing uploads reference
    video any more — a future video-reference feature must read it from here, not hardcode it.
    """

    max_image_urls: int = 0
    max_video_urls: int = 0
    max_image_bytes: int = 0
    max_video_bytes: int = 0
    video_seconds_each: tuple[int, int] = (0, 0)
    video_seconds_total: int = 0
    video_pixel_window: tuple[int, int] = (0, 0)  # inclusive width*height bounds
    video_dimension_range: tuple[int, int] = (0, 0)  # per side, px
    video_aspect_range: tuple[float, float] = (0.0, 0.0)
    video_fps_range: tuple[int, int] = (0, 0)
    video_formats: tuple[str, ...] = ()
    max_prompt_chars: int = 0  # 50 §7's truncation trigger; 0 = never truncate


@dataclass(frozen=True, slots=True)
class RenderProfile:
    """One model family: how to name its parameters, what it accepts, which prompts it wants."""

    name: str
    kind: Literal["image", "video"]  # picks image_job_timeout_s vs video_job_timeout_s
    template_set: str  # `prompts/<set>/` (FR-181); 50-promptcraft owns the set's contents
    model_id: str  # reference-bearing route, overridable from config (FR-270)
    model_id_no_refs: str  # FR-241's second route; empty when the family has only one
    limits: ReferenceLimits
    builder: Callable[[RenderParams, RenderRefs, str, str], tuple[str, dict[str, Any]]]

    def request(self, params: RenderParams, refs: RenderRefs, model_id: str = "") -> tuple[str, dict[str, Any]]:
        """Returns `(provider model route, provider input object)` for exactly one job.

        `model_id` is the configured route for this profile; empty falls back to the declared
        default so a direct call still works. Reference lists are capped and out-of-range values
        clamped in here, so the caller never has to know the family's ceilings.
        """
        return self.builder(params, refs, model_id or self.model_id, self.model_id_no_refs)


def _build_gpt_image_2(
    params: RenderParams, refs: RenderRefs, model_id: str, model_id_no_refs: str
) -> tuple[str, dict[str, Any]]:
    """GPT Image 2, both routes (FR-240/241). Keys are exactly `prompt`, `input_urls`,
    `aspect_ratio`, `resolution` — nothing else is accepted (RESULTS.md §B)."""
    ratio = params.aspect_ratio or "auto"
    urls = list(refs.image_urls[: GPT_IMAGE_2_LIMITS.max_image_urls])
    body: dict[str, Any] = {"prompt": params.prompt}
    if urls:
        body["input_urls"] = urls
    body["aspect_ratio"] = ratio
    body["resolution"] = _image_resolution(ratio, params.resolution)
    return (model_id if urls else (model_id_no_refs or model_id)), body


def _build_seedance_2_5(
    params: RenderParams, refs: RenderRefs, model_id: str, _model_id_no_refs: str
) -> tuple[str, dict[str, Any]]:
    """Seedance 2.5 (20 §8a + RESULTS.md §C's verbatim working body).

    `aspect_ratio` is always sent explicitly — the provider default is `adaptive` (D10) — and
    `nsfw_checker` likewise, because the provider defaults it to false while the engine's
    default is true (FR-166); both are forwarded uninterpreted.
    """
    body: dict[str, Any] = {"prompt": params.prompt}
    if refs.image_urls:
        body["reference_image_urls"] = list(refs.image_urls[: SEEDANCE_LIMITS.max_image_urls])
    if refs.video_urls:
        body["reference_video_urls"] = list(refs.video_urls[: SEEDANCE_LIMITS.max_video_urls])
    body["duration"] = _clamped_duration(params.duration_s)
    body["resolution"] = (params.resolution or "720p").lower()
    body["aspect_ratio"] = params.aspect_ratio or "9:16"
    body["generate_audio"] = bool(params.generate_audio)
    body["nsfw_checker"] = True if params.moderation_enabled is None else bool(params.moderation_enabled)
    body["output_format"] = (params.output_format or "mp4").lower()
    return model_id, body


def _image_resolution(aspect_ratio: str, requested: str | None) -> str:
    """Kie's `1K`/`2K`/`4K` enum, clamped to what the ratio can legally carry (20 §8c)."""
    resolution = (requested or "1K").upper()
    if resolution not in _IMAGE_RESOLUTIONS:
        resolution = "1K"
    if aspect_ratio in _ONE_K_ONLY_RATIOS:
        return "1K"
    # FR-192: 4K is declared by the enum but never requested — the ceiling is 2K (which also
    # subsumes 20 §8c's 1:1-at-4K task-creation refusal).
    return _IMAGE_RESOLUTION_CEILING if resolution == "4K" else resolution


def _clamped_duration(seconds: int | None) -> int:
    low, high = SEEDANCE_DURATION_RANGE
    return max(low, min(high, int(seconds or _SEEDANCE_DEFAULT_DURATION_S)))


GPT_IMAGE_2_LIMITS = ReferenceLimits(max_image_urls=16,  # `input_urls` maxItems 16, URLs only
                                     max_prompt_chars=MAX_PROMPT_CHARS)
SEEDANCE_LIMITS = ReferenceLimits(
    max_prompt_chars=MAX_PROMPT_CHARS,
    max_image_urls=30,
    max_video_urls=10,
    max_image_bytes=30 * 1024 * 1024,
    max_video_bytes=200 * 1024 * 1024,
    video_seconds_each=(2, 30),
    video_seconds_total=30,
    video_pixel_window=(409_600, 927_408),
    video_dimension_range=(300, 6000),
    video_aspect_range=(0.4, 2.5),
    video_fps_range=(24, 60),
    video_formats=("mp4", "mov"),
)

PROFILES: dict[str, RenderProfile] = {
    GPT_IMAGE_2: RenderProfile(
        name=GPT_IMAGE_2,
        kind="image",
        template_set=GPT_IMAGE_2,
        model_id=_GPT_IMAGE_2_REF_ROUTE,
        model_id_no_refs=_GPT_IMAGE_2_TEXT_ROUTE,
        limits=GPT_IMAGE_2_LIMITS,
        builder=_build_gpt_image_2,
    ),
    SEEDANCE_2_5: RenderProfile(
        name=SEEDANCE_2_5,
        kind="video",
        template_set=SEEDANCE_2_5,
        model_id=_SEEDANCE_ROUTE,
        model_id_no_refs="",
        limits=SEEDANCE_LIMITS,
        builder=_build_seedance_2_5,
    ),
}

PROFILE_NAMES: tuple[str, ...] = tuple(PROFILES)


def get(name: str) -> RenderProfile:
    """The profile for `name`, or `UnknownProfileError` — never a fallback to another family."""
    try:
        return PROFILES[name]
    except KeyError:
        raise UnknownProfileError(
            f"no render profile {name!r}; known profiles: {', '.join(PROFILE_NAMES)}"
        ) from None


__all__ = [
    "GPT_IMAGE_2", "MAX_PROMPT_CHARS", "PROFILES", "PROFILE_NAMES", "ReferenceLimits",
    "RenderProfile",
    "SEEDANCE_2_5", "SEEDANCE_DURATION_RANGE", "UnknownProfileError", "get",
]
