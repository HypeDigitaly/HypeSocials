"""Declarative render-model profiles — the only place a provider's parameter names live.

Purpose: turn the engine's standard render inputs (`RenderParams` + `RenderRefs`) into one
provider request — route id plus `input` object — and declare each family's reference limits and
prompt template set (FR-272). Pure data and pure functions: no I/O, no config, no logging. Field
shapes are copied verbatim from the live requests in `spikes/RESULTS.md` §B and §C.
Public API: `get(name)` · `RenderProfile` · `ReferenceLimits` · `UnknownProfileError` ·
`PROFILE_NAMES`.
Invariants:
- One profile carries BOTH GPT Image 2 routes (FR-241) — reference-bearing to image-to-image with
  `input_urls`, reference-free to text-to-image. No route name is spoken outside this file, and
  no single config key may collapse the two: each route has its own override (`models.image` for
  the reference-free one, `models.image_edit` for the reference-bearing one, FR-241 as amended
  v2.1.3/D48), because one key overriding both is the live defect that sent every anchor-chained
  slide to text-to-image with its reference attached and ignored.
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

# Kie route ids. These are the profile's DECLARATION of the family's routes (FR-272). Each route
# has its OWN config override (FR-270/FR-280 as amended v2.1.3): `models.image` names the
# reference-free route, `models.image_edit` the reference-bearing one, and `models.video` names
# a single-route family's only route. Anything a config leaves empty falls back to the id declared
# here, so a run with no overrides at all still routes both halves of FR-241 correctly.
_GPT_IMAGE_2_REF_ROUTE = "gpt-image-2-image-to-image"
_GPT_IMAGE_2_TEXT_ROUTE = "gpt-image-2-text-to-image"
_SEEDANCE_ROUTE = "bytedance/seedance-2-5"

_IMAGE_RESOLUTIONS = ("1K", "2K", "4K")
#: 1K-only ratios, plus `auto`/unset which renders 1K whatever else is asked for (20 §8c).
_ONE_K_ONLY_RATIOS = frozenset({"", "auto", "5:4", "4:5", "3:1", "1:3", "9:21"})
#: FR-192's production ceiling, enforced where the parameter is built rather than trusted from
#: config: above 2K the model is documented unstable, and 1:1 at 4K fails task creation outright.
_IMAGE_RESOLUTION_CEILING = "2K"

#: 50 §7 states the truncation ORDER but no number. This one is no longer an engine preference:
#: run `20260814_010814_glz0` MEASURED the provider's hard limit at exactly 20 000 characters —
#: every createTask with a prompt of 20 000 characters or fewer was accepted, and every one at
#: 20 007 or more came back HTTP 500 `"The text length cannot exceed the maximum limit"`. Six
#: slides were lost and three quality re-renders blocked to establish that boundary, because the
#: engine's bound was set AT the limit and a prompt still over it after truncation shipped whole
#: into a deterministic 500 (and FR-317 then resubmitted the identical bytes for a second one).
#:
#: 19 800 leaves a 200-character margin under the measured wall. The margin is deliberate slack,
#: not superstition: the caller's suffix (FR-193's retry instruction), a provider-side prompt
#: preamble or one multi-byte counting difference all land inside it, and 200 characters of style
#: prose is worth less than one slide that never submits.
#:
#: History: 10 000 at W3 (D46), 16 000 then 20 000 at v2.1.3/D48 — that last raise was made to
#: hold a MEASURED 17 757-character body slide (anchor block, TOOL MARKS rules, mark-patch role
#: lines and a 300-char verbatim panel, all of it payload) without cutting the style trio. That
#: reasoning still stands and the trio is still not cuttable by the ordinary pass; what changed at
#: v2.1.4 is the endgame, in `prompts_engine._shrink`: past this bound the trio is tail-trimmed as
#: a LAST RESORT rather than the prompt shipping over the wall (FR-241's i2i route means the
#: anchor reference carries the deck's look on body slides, so trimmed style prose is recoverable
#: — a slide that never submits is not).
MAX_PROMPT_CHARS = 19_800

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
    model_id: str  # reference-bearing route (a single-route family's only route), config `image_edit`
    model_id_no_refs: str  # FR-241's second route, config `image`; empty = the family has only one
    limits: ReferenceLimits
    builder: Callable[[RenderParams, RenderRefs, str, str], tuple[str, dict[str, Any]]]

    @property
    def dual_route(self) -> bool:
        """True when this family splits reference-bearing and reference-free jobs (FR-241).

        The one thing a caller may ask about routing without learning a route NAME: it decides
        which config key overrides which half, and `render/__init__.py` needs the answer to pass
        two configured ids instead of one.
        """
        return bool(self.model_id_no_refs)

    def request(
        self, params: RenderParams, refs: RenderRefs, model_id: str = "", model_id_edit: str = "",
    ) -> tuple[str, dict[str, Any]]:
        """Returns `(provider model route, provider input object)` for exactly one job.

        `model_id` is the configured id for this family's DEFAULT route and `model_id_edit` the
        configured id for its reference-bearing one (FR-241 as amended v2.1.3/D48 — `models.image`
        and `models.image_edit`). Either may be empty and then the profile's own declaration
        stands, so a direct call with no config at all still routes both halves correctly.

        On a SINGLE-route family (Seedance) there is no split to preserve: whichever id the caller
        configured names that family's one route, which is what keeps `models.video` working
        through the same two-argument seam.

        Reference lists are capped and out-of-range values clamped in here, so the caller never
        has to know the family's ceilings.
        """
        if self.dual_route:
            return self.builder(params, refs, model_id_edit or self.model_id,
                                model_id or self.model_id_no_refs)
        route = model_id or model_id_edit or self.model_id
        return self.builder(params, refs, route, route)


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
