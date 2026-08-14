"""FR-241's two GPT Image 2 routes, and the config keys that override them (amended v2.1.3/D48).

One profile carries BOTH halves of the gpt-image-2 family: a job with references goes to
image-to-image with `input_urls`, a job without goes to text-to-image. No route NAME is spoken
outside `render/profiles.py`, which is why the routing decision has to be pinned here — every other
surface in the codebase is deliberately blind to it.

**The live defect this file exists for.** Until v2.1.3 a single config key (`models.image`)
overrode BOTH routes, so any config that named an image model at all sent reference-BEARING jobs to
text-to-image. Kie accepts that request, ignores the attached reference and returns a picture, so
run `20260813_222101_g1xt` paid for a full carousel whose slides 2–N carried the anchor and were
rendered as if they had not: no chain, no shared design, no error anywhere. FR-241 as amended
splits the override in two — `models.image` names the reference-free route, `models.image_edit` the
reference-bearing one — and each falls back to the profile's own declaration, so a run with no
overrides at all still routes both halves correctly.

Pinned below:

1. the route each job SHAPE takes, with and without config overrides (the table);
2. the D48 defect specifically — a legacy config that overrides only `image` may not drag a
   reference-bearing job onto text-to-image;
3. the single-route family (Seedance) is untouched by the split: whichever id was configured names
   its one route, so `models.video` keeps working through the same two-argument seam;
4. the two ids really do reach the seam from config, through `runner._configure_providers`.

Provider-free: `RenderProfile.request` is a pure function of params, refs and two ids. Nothing here
opens a socket, needs a key or spends.
"""

from __future__ import annotations

import inspect

import pytest

from hypesocials import render, runner
from hypesocials.config import Config
from hypesocials.models import RenderParams, RenderRefs
from hypesocials.render import profiles

#: The family's two declared routes. Named here — the ONE place outside the profile module that
#: may — so a rename of either is a failure with a diff rather than a silently different picture.
T2I = "gpt-image-2-text-to-image"
I2I = "gpt-image-2-image-to-image"
SEEDANCE = "bytedance/seedance-2-5"

ANCHOR = "https://kie.test/upload/anchor.png"
PATCH = "https://kie.test/upload/notion.png"


def params(**overrides: object) -> RenderParams:
    base = RenderParams(prompt="one slide of a carousel", aspect_ratio="1:1", resolution="2K")
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


# ------------------------------------------------------------------ the route table (FR-241)


@pytest.mark.parametrize(
    ("image_urls", "configured_image", "configured_edit", "expected"),
    [
        # No overrides at all: the profile's own declarations route both halves. This is the row
        # that makes a default config correct without the operator knowing routes exist.
        ((), "", "", T2I),
        ((ANCHOR,), "", "", I2I),
        # Both keys configured, as the shipped configs do: each names its own half.
        ((), "kie/t2i-pinned", "kie/i2i-pinned", "kie/t2i-pinned"),
        ((ANCHOR,), "kie/t2i-pinned", "kie/i2i-pinned", "kie/i2i-pinned"),
        # `image_edit` alone: the reference-free half keeps its declared route.
        ((), "", "kie/i2i-pinned", T2I),
        ((ANCHOR,), "", "kie/i2i-pinned", "kie/i2i-pinned"),
        # A whole reference SET — the anchor plus FR-315's mark patches — is still one job with
        # references, and one route decision.
        ((ANCHOR, PATCH, PATCH), "", "", I2I),
    ])
def test_the_route_follows_the_jobs_references_and_each_half_has_its_own_override(
    image_urls: tuple[str, ...], configured_image: str, configured_edit: str, expected: str,
) -> None:
    """FR-241: the SHAPE of the job picks the route, and config may only rename the route it picked.

    `input_urls` is present exactly when the job carries references, because that is the one key
    that distinguishes the two request bodies — a reference-free body with an empty `input_urls`
    array is a different request to the same endpoint, and RESULTS.md §B accepts exactly four keys.
    """
    profile = profiles.get(profiles.GPT_IMAGE_2)

    model_id, body = profile.request(params(), RenderRefs(image_urls=list(image_urls)),
                                     configured_image, configured_edit)

    assert model_id == expected
    assert ("input_urls" in body) is bool(image_urls)
    assert body.get("input_urls", []) == list(image_urls)
    assert sorted(body) == sorted(["prompt", "aspect_ratio", "resolution"]
                                  + (["input_urls"] if image_urls else []))


def test_fr241_a_legacy_config_naming_only_models_image_cannot_pull_a_chained_slide_onto_t2i(
) -> None:
    """The defect, in the exact shape a real config produces it.

    An operator config written before v2.1.3 names `models.image` and nothing else. Under the old
    single-key seam that id reached BOTH routes, so every anchor-chained slide went to
    text-to-image carrying an `input_urls` array the endpoint accepted and ignored — a paid deck
    with no chain and no error. The amended seam gives that key the reference-FREE route only; the
    reference-bearing half falls back to the profile's declaration, which is the correct route
    whatever the config forgot to say.
    """
    profile = profiles.get(profiles.GPT_IMAGE_2)
    legacy = "kie/google-nano-banana"  # one key, the shape of every pre-D48 config

    free_route, _ = profile.request(params(), RenderRefs(), legacy, "")
    chained_route, chained_body = profile.request(
        params(), RenderRefs(image_urls=[ANCHOR]), legacy, "")

    assert free_route == legacy, "the key still names the half it was always about"
    assert chained_route == I2I, "and it may NOT name the other half"
    assert chained_route != legacy
    assert chained_body["input_urls"] == [ANCHOR], "the reference travels either way"


def test_the_profile_declares_which_family_splits_and_seedance_does_not() -> None:
    """`dual_route` is the ONE routing question a caller may ask without learning a route name.

    `render.run` needs the answer to decide whether passing two configured ids means anything, and
    the alternative — branching on the profile's NAME at the call site — is how a second family
    would silently inherit gpt-image-2's key mapping.
    """
    assert profiles.get(profiles.GPT_IMAGE_2).dual_route is True
    assert profiles.get(profiles.SEEDANCE_2_5).dual_route is False
    assert profiles.get(profiles.GPT_IMAGE_2).model_id_no_refs == T2I
    assert profiles.get(profiles.SEEDANCE_2_5).model_id_no_refs == ""


@pytest.mark.parametrize(
    ("configured_video", "configured_edit", "expected"),
    [("", "", SEEDANCE), ("kie/seedance-pinned", "", "kie/seedance-pinned"),
     # A single-route family has no split to preserve, so whichever id the caller configured names
     # its one route — which is what keeps `models.video` working through the two-argument seam.
     ("", "kie/seedance-pinned", "kie/seedance-pinned")])
def test_a_single_route_family_is_untouched_by_the_split(
    configured_video: str, configured_edit: str, expected: str,
) -> None:
    """FR-44/FR-241: Seedance has one route, with or without reference images, and the D48 change
    may not have quietly given it a second one. The reference images still ride, under Seedance's
    own key (`reference_image_urls`, not `input_urls`) — the two families never share a body."""
    profile = profiles.get(profiles.SEEDANCE_2_5)

    model_id, body = profile.request(
        params(prompt="a five second clip", aspect_ratio="9:16", duration_s=5),
        RenderRefs(image_urls=[ANCHOR]), configured_video, configured_edit)

    assert model_id == expected
    assert body["reference_image_urls"] == [ANCHOR] and "input_urls" not in body


# ------------------------------------------------------- the two ids reach the seam from config


def test_both_config_keys_are_wired_into_the_render_settings_the_runner_builds() -> None:
    """The wiring, asserted at the source rather than through a live run.

    `RenderSettings` carries two mappings for a reason, and a `configure()` call that filled only
    the first would reproduce the D48 defect with the split in place — the profile would be handed
    an empty `model_id_edit` on every job and fall back to its declaration, which is correct today
    and silently ignores `models.image_edit` forever. So both keys are pinned by NAME at the one
    call site that builds them.
    """
    settings = render.RenderSettings()
    assert settings.model_ids == {} and settings.edit_model_ids == {}

    source = inspect.getsource(runner._configure_providers)
    assert "model_ids={config.models.image_profile: config.models.image," in source
    assert "edit_model_ids={config.models.image_profile: config.models.image_edit}" in source
    # `render.run` must then hand BOTH through to the profile, in that order.
    call = inspect.getsource(render.run)
    assert 'settings.model_ids.get(profile, ""), settings.edit_model_ids.get(profile, "")' in call


def test_the_shipped_default_config_names_both_routes_and_they_are_not_the_same_id() -> None:
    """A config whose two image keys hold the same id is a config that has re-collapsed the split.

    It would still route by shape (the profile does that), but it would send image-to-image
    requests to a text-to-image endpoint under an operator-supplied name — which is the failure
    dressed as a configuration choice, and the one this default is written to prevent.
    """
    models = Config().models

    assert models.image and models.image_edit
    assert models.image != models.image_edit
    assert {models.image, models.image_edit} == {T2I, I2I}
