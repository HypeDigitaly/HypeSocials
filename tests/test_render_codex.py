"""The codex render provider: the same seam, a subscription instead of an invoice (D64).

`render_provider: codex` swaps Kie.ai for the operator's ChatGPT subscription, reached through the
local `npx openai-oauth@latest` proxy. Nothing downstream may notice: the gate, the ledger hooks,
`RenderOutcome` and `meta.yaml` are provider-blind, and a slide that renders here has to arrive on
disk exactly as a Kie slide does.

Pinned below, and each of these is a way a live run would have failed silently:

1. the ENDPOINT follows the job's shape — references send multipart to `/images/edits`, a bare
   prompt sends JSON to `/images/generations` — and the model id sent is always `gpt-image-2`,
   never the configured Kie route name;
2. reference ORDER survives into the multipart body (FR-95/24: the chained anchor leads), and a
   non-`file://` URL is dropped rather than fetched (D41/D46: this client pulls nothing);
3. a landed render is a LOCAL FILE plus a `file://` URL at $0, with the FR-203 hooks in order;
4. the failure vocabulary is the seam's, not the proxy's: moderation is `MODERATION` (FR-97's
   retry depends on that class), a timeout is `STUCK`/`TIMEOUT` (FR-317's single resubmit depends
   on it), 429 retries and then succeeds, an unreachable proxy names the command that starts it;
5. a VIDEO body is a stated FAIL, never an exception and never a silent picture;
6. `configure(provider="codex")` reads NO environment variable — there is no key to have;
7. `packager._download()` reads a `file://` URL off the disk with the same error vocabulary it
   uses for a dead CDN URL.

No network: every test drives an `httpx.MockTransport`. No key: the codex path has none.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from hypesocials import render
from hypesocials.models import (
    RenderFailCause, RenderOutcomeKind, RenderParams, RenderRefs,
)
from hypesocials.outputs import packager
from hypesocials.render import codex_images, profiles
from hypesocials.render.codex_images import CodexImageClient, CodexUploadError

PNG = b"\x89PNG\r\n\x1a\n" + b"pretend pixels"
GENERATIONS = "/images/generations"
EDITS = "/images/edits"


# ------------------------------------------------------------------ helpers


class Recorder:
    """A stand-in for `outputs.LogWriter` — only `event()` is ever called from the client."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def event(self, event_type: str, message: str = "", **data: Any) -> str:
        self.events.append((event_type, message, data))
        return "ev_test"

    def types(self) -> list[str]:
        return [event_type for event_type, _, _ in self.events]


def image_body(prompt: str = "one slide", ratio: str = "1:1", refs: tuple[str, ...] = ()) -> dict:
    """The REAL gpt-image-2 body, built by the profile — never a hand-typed dict.

    The client's video guard reads body KEYS, so a test that invented its own body could pass
    while the shipped one fell through the guard.
    """
    _, body = profiles.get(profiles.GPT_IMAGE_2).request(
        RenderParams(prompt=prompt, aspect_ratio=ratio, resolution="2K"),
        RenderRefs(image_urls=list(refs)))
    return body


def video_body() -> dict:
    _, body = profiles.get(profiles.SEEDANCE_2_5).request(
        RenderParams(prompt="a five second clip", aspect_ratio="9:16", duration_s=5),
        RenderRefs())
    return body


def answer(blob: bytes = PNG) -> httpx.Response:
    return httpx.Response(200, json={
        "data": [{"b64_json": base64.b64encode(blob).decode("ascii")}],
        "usage": {"input_tokens": 37, "output_tokens": 229, "total_tokens": 266},
    })


def client(handler: Any, tmp_path: Path | None = None, log: Any = None,
           **kwargs: Any) -> CodexImageClient:
    return CodexImageClient(
        scratch_dir=tmp_path, log=log,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kwargs)


def hooks() -> tuple[list[tuple], Any, Any]:
    calls: list[tuple] = []
    return calls, (lambda token: calls.append(("intent", token))), (
        lambda token, task_id: calls.append(("submitted", token, task_id)))


# ------------------------------------------------------------------ 1. endpoint and model


async def test_a_reference_free_job_posts_json_to_generations_as_gpt_image_2(tmp_path: Path) -> None:
    """The configured Kie route name is recorded and NOT sent: this API routes by endpoint."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return answer()

    codex = client(handler, tmp_path)
    outcome = await codex.render("gpt-image-2-text-to-image", image_body(ratio="4:5"),
                                 timeout_s=60)
    await codex.aclose()

    assert outcome.kind is RenderOutcomeKind.SUCCESS
    assert seen["path"].endswith(GENERATIONS)
    assert seen["content_type"].startswith("application/json")
    assert seen["body"] == {"model": "gpt-image-2", "prompt": "one slide",
                            "size": "1024x1536", "n": 1}
    # D30: there is no key on this path, so there must be no header pretending there is one.
    assert seen["auth"] is None


@pytest.mark.parametrize(("ratio", "size"), [
    ("1:1", "1024x1024"), ("auto", "1024x1024"), ("", "1024x1024"), ("21:9", "1024x1024"),
    ("4:5", "1024x1536"), ("9:16", "1024x1536"), ("2:3", "1024x1536"), ("3:4", "1024x1536"),
    ("16:9", "1536x1024"), ("3:2", "1536x1024"), ("4:3", "1536x1024"), ("5:4", "1536x1024"),
])
def test_every_engine_aspect_ratio_maps_to_a_standard_openai_size(ratio: str, size: str) -> None:
    """Pure mapping. An unknown ratio renders square rather than refusing a paid-for creative."""
    assert codex_images._size_for(ratio) == size


# ------------------------------------------------------------------ 2. references


async def test_references_travel_as_multipart_image_parts_in_the_order_they_were_given(
    tmp_path: Path,
) -> None:
    """FR-95/24: the chained anchor leads the list, and it must still lead in the request body."""
    anchor = tmp_path / "anchor.png"
    patch = tmp_path / "notion_mark.png"
    anchor.write_bytes(b"anchor-bytes")
    patch.write_bytes(b"patch-bytes")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["content_type"] = request.headers.get("content-type", "")
        seen["raw"] = request.content
        return answer()

    codex = client(handler, tmp_path)
    outcome = await codex.render(
        "gpt-image-2-image-to-image",
        image_body(refs=(anchor.as_uri(), patch.as_uri())), timeout_s=60)
    await codex.aclose()

    assert outcome.kind is RenderOutcomeKind.SUCCESS
    assert seen["path"].endswith(EDITS)
    assert seen["content_type"].startswith("multipart/form-data")
    raw = seen["raw"]
    assert raw.count(b'name="image[]"') == 2
    assert raw.index(b"anchor-bytes") < raw.index(b"patch-bytes")
    for field in (b'name="prompt"', b'name="model"', b'name="size"', b'name="n"'):
        assert field in raw
    assert b"gpt-image-2" in raw


async def test_a_non_file_reference_is_dropped_and_never_fetched(tmp_path: Path) -> None:
    """The one rule that keeps a Virlo CDN slide out of a render payload (D41/D46).

    A URL this client cannot read off the disk is left out with a warned line — it is NOT
    downloaded and turned into a reference, which is exactly the door the source store must not
    have.
    """
    log = Recorder()
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return answer()

    codex = client(handler, tmp_path, log=log)
    outcome = await codex.render(
        "gpt-image-2-image-to-image",
        image_body(refs=("https://virlo.cdn/slide_02.jpg",)), timeout_s=60)
    await codex.aclose()

    assert outcome.kind is RenderOutcomeKind.SUCCESS
    # Nothing left to attach -> the reference-free endpoint, not an edit with zero images.
    assert seen["path"].endswith(GENERATIONS)
    assert "codex_reference_dropped" in log.types()


# ------------------------------------------------------------------ 3. the landed render


async def test_a_landed_render_is_a_local_png_a_file_url_and_zero_dollars(tmp_path: Path) -> None:
    log = Recorder()
    calls, on_intent, on_submitted = hooks()

    codex = client(lambda request: answer(), tmp_path, log=log)
    outcome = await codex.render("gpt-image-2-text-to-image", image_body(), timeout_s=60,
                                 on_intent=on_intent, on_submitted=on_submitted)
    await codex.aclose()

    assert outcome.kind is RenderOutcomeKind.SUCCESS
    assert outcome.cost_usd == 0.0
    assert outcome.task_id and outcome.task_id.startswith("codex-")
    assert outcome.submitted_at and outcome.completed_at and outcome.elapsed_s >= 0.0

    stored = tmp_path / codex_images.RENDERS_DIR / f"{outcome.task_id}.png"
    assert stored.read_bytes() == PNG
    assert outcome.result_urls == [stored.as_uri()]
    # The packager decides file names off the URL; a `.renders/*.png` URI must still say `.png`.
    assert packager._extension(outcome.result_urls[0]) == ".png"

    # FR-203: intent BEFORE the request, the id afterwards, same token on both.
    assert [call[0] for call in calls] == ["intent", "submitted"]
    assert calls[0][1] == calls[1][1] == outcome.request_token
    assert calls[1][2] == outcome.task_id
    assert log.types()[-1] == "codex_job_result"
    assert "codex_job_submitted" in log.types()


async def test_the_fixed_proxy_size_is_reported_once_per_run_not_once_per_slide(
    tmp_path: Path,
) -> None:
    """FR-342 lets a platform pin `2k`; this provider cannot honour it and says so — once."""
    log = Recorder()
    codex = client(lambda request: answer(), tmp_path, log=log)
    for _ in range(3):
        await codex.render("gpt-image-2-text-to-image", image_body(), timeout_s=60)
    await codex.aclose()

    assert log.types().count("codex_resolution_fixed") == 1


async def test_a_two_hundred_with_no_image_in_it_is_empty_result_urls(tmp_path: Path) -> None:
    """The FR-242 rule, carried over: a green status is not a picture."""
    codex = client(lambda request: httpx.Response(200, json={"data": []}), tmp_path)
    outcome = await codex.render("gpt-image-2-text-to-image", image_body(), timeout_s=60)
    await codex.aclose()

    assert outcome.kind is RenderOutcomeKind.FAIL
    assert outcome.fail_cause is RenderFailCause.EMPTY_RESULT_URLS
    assert not outcome.result_urls
    assert not (tmp_path / codex_images.RENDERS_DIR).exists()  # nothing half-written


# ------------------------------------------------------------------ 4. the failure vocabulary


async def test_a_moderation_refusal_keeps_its_own_cause(tmp_path: Path) -> None:
    """FR-97 retries ONCE on moderation and on nothing else, so the class has to survive."""
    body = {"error": {"message": "Your request was rejected by our content_policy filter.",
                      "type": "invalid_request_error"}}
    codex = client(lambda request: httpx.Response(400, json=body), tmp_path)
    outcome = await codex.render("gpt-image-2-text-to-image", image_body(), timeout_s=60)
    await codex.aclose()

    assert outcome.kind is RenderOutcomeKind.FAIL
    assert outcome.fail_cause is RenderFailCause.MODERATION
    assert "content_policy" in outcome.fail_message


async def test_an_ordinary_four_hundred_is_a_provider_fail_carrying_the_proxys_own_words(
    tmp_path: Path,
) -> None:
    codex = client(
        lambda request: httpx.Response(400, json={"error": {"message": "unknown parameter: n"}}),
        tmp_path)
    outcome = await codex.render("gpt-image-2-text-to-image", image_body(), timeout_s=60)
    await codex.aclose()

    assert outcome.kind is RenderOutcomeKind.FAIL
    assert outcome.fail_cause is RenderFailCause.PROVIDER_FAIL
    assert "unknown parameter" in outcome.fail_message


async def test_a_429_is_retried_with_backoff_and_the_render_still_lands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A quota blip must cost a second, not a slide. Backoff is flattened, not skipped."""
    monkeypatch.setattr(codex_images, "_BACKOFF_BASE_S", 0.0)
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"retry-after": "0"},
                                  json={"error": {"message": "slow down"}})
        return answer()

    codex = client(handler, tmp_path)
    outcome = await codex.render("gpt-image-2-text-to-image", image_body(), timeout_s=60)
    await codex.aclose()

    assert len(attempts) == 2
    assert outcome.kind is RenderOutcomeKind.SUCCESS


async def test_a_read_timeout_is_stuck_with_the_timeout_cause(tmp_path: Path) -> None:
    """STUCK/TIMEOUT is what FR-317's single resubmit reads — a FAIL here would burn nothing."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    codex = client(handler, tmp_path)
    outcome = await codex.render("gpt-image-2-text-to-image", image_body(), timeout_s=60)
    await codex.aclose()

    assert outcome.kind is RenderOutcomeKind.STUCK
    assert outcome.fail_cause is RenderFailCause.TIMEOUT


async def test_a_job_with_no_time_left_never_posts_at_all(tmp_path: Path) -> None:
    """The run deadline shows up here as a zero budget: no request, still a terminal outcome."""
    posts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(1)
        return answer()

    codex = client(handler, tmp_path)
    outcome = await codex.render("gpt-image-2-text-to-image", image_body(), timeout_s=0)
    await codex.aclose()

    assert not posts
    assert outcome.kind is RenderOutcomeKind.STUCK
    assert outcome.fail_cause is RenderFailCause.TIMEOUT


async def test_an_unreachable_proxy_names_the_command_that_starts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(codex_images, "_BACKOFF_BASE_S", 0.0)
    tries: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        tries.append(1)
        raise httpx.ConnectError("connection refused", request=request)

    codex = client(handler, tmp_path, http_max_attempts=2)
    outcome = await codex.render("gpt-image-2-text-to-image", image_body(), timeout_s=60)
    await codex.aclose()

    assert len(tries) == 2  # bounded by http_max_attempts, not by the job timeout
    assert outcome.kind is RenderOutcomeKind.FAIL
    assert outcome.fail_cause is RenderFailCause.PROVIDER_FAIL
    assert "npx openai-oauth@latest" in outcome.fail_message


# ------------------------------------------------------------------ 5. video


async def test_a_video_body_is_a_stated_failure_and_never_an_exception(tmp_path: Path) -> None:
    """There is no subscription path for video. The reel degrades; the run does not crash."""
    calls, on_intent, on_submitted = hooks()
    posts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(1)
        return answer()

    codex = client(handler, tmp_path)
    outcome = await codex.render("bytedance/seedance-2-5", video_body(), timeout_s=300,
                                 on_intent=on_intent, on_submitted=on_submitted)
    await codex.aclose()

    assert not posts
    assert outcome.kind is RenderOutcomeKind.FAIL
    assert outcome.fail_cause is RenderFailCause.PROVIDER_FAIL
    assert outcome.fail_message == codex_images.VIDEO_REFUSAL
    assert [call[0] for call in calls] == ["intent", "submitted"]
    assert calls[1][2] is None  # nothing was ever submitted, so the ledger says so


# ------------------------------------------------------------------ 6. configure + upload


async def test_configure_on_codex_needs_no_key_and_upload_returns_a_file_uri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of the subscription path: no key exists, so none may be required."""
    monkeypatch.delenv("KIE_API_KEY", raising=False)
    source = tmp_path / "marks" / "notion.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"logo patch")

    render.configure(render.RenderSettings(
        provider=render.PROVIDER_CODEX, scratch_dir=tmp_path,
        base_url="http://127.0.0.1:10531/v1"))
    try:
        url = await render.upload_file(source)
    finally:
        await render.aclose()

    assert url == source.resolve().as_uri()
    assert url.startswith("file:///")


async def test_configure_on_kie_still_demands_its_key_and_an_unknown_provider_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The codex branch must not have loosened the metered one, and there is no third default."""
    monkeypatch.delenv("KIE_API_KEY", raising=False)
    with pytest.raises(render.RenderError, match="KIE_API_KEY"):
        render.configure(render.RenderSettings())
    with pytest.raises(render.RenderError, match="unknown render provider"):
        render.configure(render.RenderSettings(provider="replicate"))


async def test_uploading_a_file_that_is_not_there_drops_that_reference_only() -> None:
    """`CodexUploadError` IS a `KieUploadError`, so every existing caller keeps its posture."""
    codex = CodexImageClient()
    try:
        with pytest.raises(render.KieUploadError):
            await codex.upload(Path("nowhere") / "missing.png")
    finally:
        await codex.aclose()

    assert issubclass(CodexUploadError, render.KieUploadError)


# ------------------------------------------------------------------ 7. the packager reads file://


async def test_the_packager_downloads_a_file_url_off_the_disk(tmp_path: Path) -> None:
    target = tmp_path / "a folder" / "codex-abc.png"
    target.parent.mkdir()
    target.write_bytes(PNG)

    assert await packager._download(target.as_uri()) == PNG


@pytest.mark.parametrize("make_it", ["missing", "empty"])
async def test_an_unreadable_file_url_fails_exactly_like_a_dead_cdn_url(
    tmp_path: Path, make_it: str,
) -> None:
    target = tmp_path / "codex-gone.png"
    if make_it == "empty":
        target.write_bytes(b"")

    with pytest.raises(packager.PackagingError) as caught:
        await packager._download(target.as_uri())

    assert caught.value.reason == "download_failed"


def test_a_relative_scratch_dir_still_mints_an_absolute_file_url(tmp_path: Path, monkeypatch: Any) -> None:
    """Canary 20260821_112153_t91p: the runner passes `output/<run>` RELATIVE to the cwd, and
    `Path.as_uri()` raises `ValueError: relative path can't be expressed as a file URI` — the
    first landed render killed the run. The client resolves the directory once at construction."""
    monkeypatch.chdir(tmp_path)
    codex = CodexImageClient(scratch_dir=Path("output") / "run_x")
    url = codex._store("codex-abc", b"\x89PNG\r\n\x1a\nxx")
    assert url.startswith("file:///")
    assert (tmp_path / "output" / "run_x" / ".renders" / "codex-abc.png").exists()
