"""D64 — the local Codex proxy seam: probe it, start it only when it is missing, never leak it.

`hypesocials/codex_proxy.py` is the one piece of SESSION O that touches a socket and a subprocess,
which makes it the one piece that can hurt an operator in ways a config error cannot: a proxy
started twice fights for a port, a proxy started off-box hands this workstation's ChatGPT sign-in
to whoever answers, and a proxy that outlives the engine keeps a node process alive after the
console closed. Every test here pins one of those.

Nothing in this file starts a real proxy, downloads an npm package or opens a real socket. The
HTTP half runs on `httpx.MockTransport` through the module's documented `client=` seam; the
subprocess half runs on a fake process object installed over `asyncio.create_subprocess_exec`, and
one test asserts that the reachable path never reaches that patch at all — "already running" is
only worth anything if it is provably spawn-free.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from hypesocials import codex_proxy
from hypesocials.codex_proxy import ProxyHandle, ProxyUnavailable, ensure_proxy, probe, stop

BASE = "http://127.0.0.1:10531/v1"
#: What the real proxy answered on 2026-08-21 — the shape `probe()` has to understand, verbatim.
MODEL_IDS = ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-5.4", "gpt-5.4-mini",
             "gpt-image-2"]


# --------------------------------------------------------------------------- fixtures & fakes


@pytest.fixture(autouse=True)
def _no_leaked_handle() -> Any:
    """Clear the module's `current_handle()` cell around every test.

    It is process-global by design (the runner's exit path reads it without a verdict object), so
    one test's handle would otherwise decide the next test's answer.
    """
    codex_proxy._CURRENT = None
    yield
    codex_proxy._CURRENT = None


@pytest.fixture(autouse=True)
def _proxy_log_in_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect `logs/codex_proxy.log` into `tmp_path` — no test may write into the repo's logs."""
    monkeypatch.setattr(codex_proxy, "LOG_PATH", tmp_path / "codex_proxy.log")


def _client(handler: Any) -> httpx.AsyncClient:
    """An `httpx.AsyncClient` on a mock transport — the seam `probe(client=…)` documents."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _serving(ids: list[str] = MODEL_IDS) -> httpx.AsyncClient:
    """A client that answers `GET /models` the way the real proxy does."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models"), request.url
        return httpx.Response(200, json={"data": [{"id": model} for model in ids]})
    return _client(handler)


def _dead() -> httpx.AsyncClient:
    """A client whose every request fails to connect — the "nothing is listening" case."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)
    return _client(handler)


class _FakeProcess:
    """The subprocess `create_subprocess_exec` would have returned, with no process behind it.

    `pid` is `None` on purpose: it makes the Windows job-object assignment and the `taskkill /T`
    sweep no-ops (both bail on a missing pid), so a unit test can exercise the launch and teardown
    ORDER without CreateJobObject ever seeing a fabricated pid.
    """

    def __init__(self, returncode: int | None = None) -> None:
        self.returncode = returncode
        self.pid = None
        self.terminated = 0
        self.waited = 0

    def terminate(self) -> None:
        self.terminated += 1
        self.returncode = -15

    async def wait(self) -> int:
        self.waited += 1
        return self.returncode or 0


def _spawns(monkeypatch: pytest.MonkeyPatch, process: _FakeProcess) -> dict[str, Any]:
    """Install `process` over `create_subprocess_exec` and record the launch it was asked for."""
    seen: dict[str, Any] = {}

    async def fake_exec(*args: Any, **kwargs: Any) -> _FakeProcess:
        seen["args"], seen["kwargs"] = args, kwargs
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(codex_proxy.shutil, "which", lambda name: r"C:\nodejs\npx.cmd")
    return seen


# --------------------------------------------------------------------------- probe


@pytest.mark.asyncio
async def test_probe_returns_the_model_ids_the_proxy_lists() -> None:
    """The happy path, and the reason `probe()` is also the CONFIG check.

    Pre-flight compares `models.analysis`/`models.copy`/the critic ids against exactly this list,
    so the order and the values are the contract: ids come back as the proxy wrote them, with no
    normalising, no prefixing and no filtering to a known set. A proxy that starts serving
    `gpt-5.7` tomorrow must not need a code change here to be usable.
    """
    async with _serving() as client:
        assert await probe(BASE, client=client) == MODEL_IDS


@pytest.mark.asyncio
async def test_probe_says_how_to_start_the_proxy_when_nothing_is_listening() -> None:
    """A connect error is `ProxyUnavailable`, and it carries the cure rather than a stack shape.

    This message is what an operator reads at 7am when a scheduled run refused, so it names both
    halves of the fix — start the proxy, and sign in — because "connection refused" alone sends
    somebody looking at their firewall.
    """
    async with _dead() as client:
        with pytest.raises(ProxyUnavailable) as raised:
            await probe(BASE, client=client)
    message = str(raised.value)
    assert BASE in message and "npx openai-oauth@latest" in message and "codex login" in message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "because"),
    [
        (httpx.Response(404, text="not found"), "a 404 is a different server, not our proxy"),
        (httpx.Response(500, text="boom"), "a 500 is a proxy that cannot serve its own list"),
        (httpx.Response(200, text="<html>hi"), "an HTML body is a captive portal, not JSON"),
        (httpx.Response(200, json={"models": ["gpt-5.6-luna"]}), "OpenAI's key is `data`"),
        (httpx.Response(200, json={"data": [{"name": "gpt-5.6-luna"}]}), "each row needs an `id`"),
        (httpx.Response(200, json={"data": []}), "up, but signed into nothing"),
    ],
)
async def test_probe_treats_every_unusable_answer_as_the_same_one_failure(
    response: httpx.Response, because: str,
) -> None:
    """Six ways to not have an endpoint, one exception type — because the caller's move is one move.

    Pre-flight grades this into a single refusal line, so splitting the failure into six classes
    would buy nothing but six branches nobody reads. What each of them DOES owe is the cure, and
    that is what is asserted: no arm may raise a bare "bad response".
    """
    async with _client(lambda request: response) as client:
        with pytest.raises(ProxyUnavailable) as raised:
            await probe(BASE, client=client)
    assert "npx openai-oauth@latest" in str(raised.value), because


# --------------------------------------------------------------------------- the loopback guard


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://10.0.0.5:10531/v1",
    "http://proxy.internal:10531/v1",
    "https://openai-oauth.example.com/v1",
    "http://0.0.0.0:10531/v1",
])
async def test_an_off_box_base_url_is_refused_before_any_socket_opens(url: str) -> None:
    """D30 applied to a credential this engine never even reads.

    The proxy speaks for the operator's own ChatGPT sign-in and needs no key from us — which is
    exactly why a typo in `models.llm_base_url` is dangerous rather than merely wrong: pointing it
    at a LAN address would send this workstation's prompts, and its session, to whatever answered.
    `ValueError` and not `ProxyUnavailable` on purpose: nothing about starting a proxy can fix it,
    the config line has to change.

    `0.0.0.0` is in the list deliberately — it is the "bind everywhere" address an operator reaches
    for when a proxy seems unreachable, and it is the single worst value this key could hold.
    """
    with pytest.raises(ValueError, match="off-box|host"):
        await probe(url)
    with pytest.raises(ValueError):
        await ensure_proxy(url)


@pytest.mark.asyncio
async def test_localhost_and_a_missing_port_are_both_accepted() -> None:
    """The two spellings an operator actually types. `localhost` is loopback; a bare host is 10531.

    A URL with no port is not an error, because there is exactly one port this proxy uses and
    guessing 80 (what a URL parser would say) would produce a confusing refusal instead of a run.
    """
    async with _serving() as client:
        assert await probe("http://localhost:10531/v1", client=client) == MODEL_IDS
    assert codex_proxy._port_of("http://127.0.0.1/v1") == codex_proxy.DEFAULT_PORT
    assert codex_proxy._port_of("http://localhost:10999/v1") == 10999


# --------------------------------------------------------------------------- ensure_proxy


@pytest.mark.asyncio
async def test_a_proxy_the_operator_already_started_is_used_and_never_re_spawned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The interactive case, and the one that must never spawn: probe first, always.

    An operator who keeps the proxy open in its own window is the normal way this is used. Starting
    a second one would fight for port 10531, and the loser's error would land in a log file nobody
    is reading. So `owned` stays False — which is also the flag `stop()` obeys, so this run cannot
    close a window it did not open.

    The assertion is structural rather than behavioural: `create_subprocess_exec` is replaced with
    a function that FAILS the test if it is ever reached.
    """
    def never(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("ensure_proxy spawned a second proxy over a running one")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", never)
    async with _serving() as client:
        handle = await ensure_proxy(BASE, client=client)

    assert handle.owned is False and handle.process is None
    assert handle.models == tuple(MODEL_IDS)
    assert handle.base_url == BASE and handle.port == 10531
    assert codex_proxy.current_handle() is handle, "pre-flight reads the handle from here"
    await stop(handle)  # a no-op on an unowned proxy, and it must still clear the cell
    assert codex_proxy.current_handle() is None


@pytest.mark.asyncio
async def test_a_missing_proxy_is_launched_with_stdin_detached_and_output_in_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The launch contract, argument by argument, because each one is a bug that already exists.

    - `stdin=DEVNULL`: the proxy offers `[d] Run in background [q] Quit` on a TTY. Attached to the
      console it would eat the keystroke the operator meant for the Confirm gate.
    - stdout/stderr to a FILE: its progress chatter must never interleave with the run's own
      console output, and it must still be readable after a failed start.
    - `--port` from the URL: the port is config's, never a constant in the launch line.
    - the resolved `npx.cmd` path: `create_subprocess_exec` with a bare `npx` finds nothing on
      Windows, since what is on PATH is the `.cmd` shim.
    """
    process = _FakeProcess()
    seen = _spawns(monkeypatch, process)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:  # first probe: nothing is listening yet, so it must launch
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={"data": [{"id": model} for model in MODEL_IDS]})

    async with _client(handler) as client:
        handle = await ensure_proxy("http://127.0.0.1:10999/v1", startup_timeout_s=5.0,
                                    client=client)

    assert handle.owned is True and handle.process is process
    assert handle.models == tuple(MODEL_IDS)
    assert seen["args"][0].lower().endswith("npx.cmd"), seen["args"]
    assert "openai-oauth@latest" in seen["args"] and "--port" in seen["args"]
    assert seen["args"][seen["args"].index("--port") + 1] == "10999"
    assert seen["kwargs"]["stdin"] is asyncio.subprocess.DEVNULL
    assert seen["kwargs"]["stdout"] is seen["kwargs"]["stderr"], "one file, both streams"
    assert (tmp_path / "codex_proxy.log").exists(), "the child's output has somewhere to go"
    await stop(handle)


@pytest.mark.asyncio
async def test_a_proxy_that_never_answers_is_killed_and_refused_not_left_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The timeout path — and the reason it is a test rather than a comment.

    A start that times out has still STARTED something. Leaving it behind would give the operator a
    half-alive node process holding the port, so the next run's probe would succeed against a proxy
    that answers nothing. So the child is terminated before the refusal is raised, the handle is
    off the module cell, and the message says where the child's own words are.
    """
    process = _FakeProcess()
    _spawns(monkeypatch, process)

    async with _dead() as client:
        with pytest.raises(ProxyUnavailable) as raised:
            await ensure_proxy(BASE, startup_timeout_s=0.0, client=client)

    assert process.terminated == 1, "the child this call started must not survive its failure"
    assert "did not answer" in str(raised.value) and "codex login" in str(raised.value)
    assert codex_proxy.current_handle() is None, "a failed start leaves no handle to stop"


@pytest.mark.asyncio
async def test_a_child_that_exits_at_once_is_reported_at_once_not_after_the_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`npx` exits in a second or two when the port is taken or the package name is wrong.

    Waiting out the full 45 s to say so would look exactly like a slow start, on the run where the
    answer was already known. The refusal names the exit code and the log file, which is where the
    child's own explanation is.
    """
    process = _FakeProcess(returncode=1)
    _spawns(monkeypatch, process)

    async with _dead() as client:
        with pytest.raises(ProxyUnavailable) as raised:
            await ensure_proxy(BASE, startup_timeout_s=600.0, client=client)  # never waited

    assert "exited immediately (code 1)" in str(raised.value)
    assert "codex_proxy.log" in str(raised.value)


@pytest.mark.asyncio
async def test_no_node_on_path_is_a_refusal_that_names_the_way_back_to_the_metered_doors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A workstation without Node cannot use the subscription — and must be told the alternative.

    The cure here is not "install Node" alone: this operator has two working metered providers one
    config line away, and a refusal that omits that leaves a paying customer stuck.
    """
    monkeypatch.setattr(codex_proxy.shutil, "which", lambda name: None)
    async with _dead() as client:
        with pytest.raises(ProxyUnavailable) as raised:
            await ensure_proxy(BASE, client=client)
    message = str(raised.value)
    assert "npx was not found on PATH" in message
    assert "llm_backend: openrouter" in message and "render_provider: kie" in message


# --------------------------------------------------------------------------- stop


@pytest.mark.asyncio
async def test_stop_is_idempotent_and_never_raises_on_any_shape_it_is_handed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It runs from `runner._cleanup()`, on EVERY exit path, including the ones already failing.

    A cleanup step that can throw turns one bad run into two bad lines, so `None`, a second call
    and a child that is already gone are all silent no-ops. The terminate count is what proves the
    second call did not fire a second kill.
    """
    process = _FakeProcess()
    _spawns(monkeypatch, process)

    def handler(request: httpx.Request) -> httpx.Response:
        if process.terminated:  # after teardown the endpoint is gone again
            raise httpx.ConnectError("gone", request=request)
        return httpx.Response(200, json={"data": [{"id": "gpt-image-2"}]})

    async with _client(handler) as client:
        handle = await ensure_proxy(BASE, client=client)
    assert handle.owned is False, "the mock answered the first probe, so nothing was spawned"

    await stop(None)  # the "we never got that far" exit path
    owned = ProxyHandle(base_url=BASE, port=10531, owned=True, process=process)
    await stop(owned)
    await stop(owned)
    assert process.terminated == 1, "the second stop must not fire a second kill"


@pytest.mark.asyncio
async def test_stop_never_touches_a_proxy_this_run_did_not_start() -> None:
    """`owned` is the whole authority, and an operator's own window is not ours to close.

    The interactive session is the reason: somebody keeps the proxy open, runs the engine four
    times in an afternoon, and the first exit must not take their proxy with it.
    """
    process = _FakeProcess()
    await stop(ProxyHandle(base_url=BASE, port=10531, owned=False, process=process))
    assert process.terminated == 0
