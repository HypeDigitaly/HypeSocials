"""20 §3 / FR-118/119 — the Virlo wrapper's query parameters: what goes on the wire, and what never can.

Three things are pinned here, in the order they cost money:

1. **The sort actually reaches Virlo.** `get_top_videos` spent this project's whole history asking for
   nothing but `limit`, so "top videos" was Virlo's insertion order — measured 2026-08-11, a median of
   2,534 views where `order_by=views&sort=desc` returns 1,940,676. A regression here is invisible in
   output (the run still succeeds, on rubbish references), so it has to be visible in a test.
2. **A bad argument is refused locally, before the HTTP call**, as one of the four FR-119 classes.
   `order_by=engagement` is the measured 400: it must never reach Virlo to come back as opaque prose.
3. **`offset` is never sent.** Virlo rejects it outright (`{"message":["property offset should not
   exist"]}`) while echoing a *derived* `offset` in its own response bodies — the one parameter name
   that looks legitimate and is not.

Everything is offline. The module's lazily-built `_client` is replaced with a recorder, so no network,
no MCP subprocess and **no `VIRLO_API_KEY`** — `_http()` never reaches the branch that reads it. The
success bodies are the real captured corpus in `tests/fixtures/virlo/` (whole, envelope included), so
normalization runs against rows with `intelligence: null`, absent hooks and positional panel images.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from mcp import MCPError

from hypesocials.virlo_mcp import ERROR_NOT_FOUND, ERROR_SERVER
from hypesocials.virlo_mcp import server as virlo_server

FIXTURES = Path(__file__).parent / "fixtures" / "virlo"

#: The monitor the captured corpus belongs to, and the one `configs/hypedigitaly.yaml` ships.
MONITOR = "9c96fddf-dc35-4be0-bbd9-12f4d22aea12"


def _body(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _Response:
    """The narrow slice of `httpx.Response` that `_get`, `_classify` and `_unwrap` actually touch."""

    is_success = True
    status_code = 200
    text = ""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _Recorder:
    """Stands in for the module-level client: records every outgoing request, answers from a fixture."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, path: str, params: dict[str, Any] | None = None) -> _Response:
        self.calls.append((path, dict(params or {})))
        return _Response(self._payload)

    @property
    def sent_params(self) -> list[dict[str, Any]]:
        return [params for _, params in self.calls]


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    """Installs the recorder as the server's one shared client, answering with the videos corpus."""
    stub = _Recorder(_body("videos_views_desc_limit100.json"))
    monkeypatch.setattr(virlo_server, "_client", stub)
    return stub


# ---------------------------------------------------------------------------------------------
# 1. Valid parameters reach the query string, and the sorted corpus survives normalization.
# ---------------------------------------------------------------------------------------------


async def test_media_params_reach_the_query_string(recorder: _Recorder) -> None:
    result = await virlo_server.get_top_videos(
        MONITOR, limit=100, page=1, order_by="views", sort="desc"
    )

    assert recorder.calls == [
        (f"/agents/{MONITOR}/videos", {"limit": 100, "page": 1, "order_by": "views", "sort": "desc"})
    ]
    # The whole point of the sort: the rows that come back are the monitor's winners, in order.
    views = [video["views"] for video in result["videos"]]
    assert views == sorted(views, reverse=True)
    assert views[0] > 10_000_000  # unsorted, the measured max over 50 rows was 83,386
    assert result["total"] == 2039  # the response's own pagination metadata, read through `_unwrap`


async def test_slideshows_take_the_same_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _Recorder(_body("slideshows_views_desc_limit100.json"))
    monkeypatch.setattr(virlo_server, "_client", stub)

    result = await virlo_server.get_top_slideshows(
        MONITOR, limit=25, page=2, order_by="publish_date", sort="asc"
    )

    assert stub.sent_params == [{"limit": 25, "page": 2, "order_by": "publish_date", "sort": "asc"}]
    assert result["slideshows"][0]["panel_count"] >= 1  # positional `images[]` still flattened


async def test_omitted_parameters_are_not_sent(recorder: _Recorder) -> None:
    """No argument means no query string at all — never `limit=None` or an empty `order_by`."""
    await virlo_server.get_top_videos(MONITOR)

    assert recorder.sent_params == [{}]


async def test_argument_free_tools_still_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_get` grew a params mapping where it took a bare `limit`; the three no-arg tools must not care."""
    monkeypatch.setattr(virlo_server, "_client", _Recorder(_body("agents.json")))
    monitors = await virlo_server.list_monitors()
    assert monitors["monitors"] and monitors["monitors"][0]["id"]

    monkeypatch.setattr(virlo_server, "_client", _Recorder(_body("agent_detail.json")))
    analysis = await virlo_server.get_monitor_analysis(MONITOR)
    assert analysis["monitor_id"] == MONITOR

    # The digest is Virlo's one metered endpoint and was deliberately never captured, so its shape
    # is spelled out here rather than fixtured (see tests/fixtures/virlo/README.md).
    digest = {"data": [{"id": "g1", "title": "Global", "trends": [{"trend": {"name": "AI agents"}}]}]}
    monkeypatch.setattr(virlo_server, "_client", _Recorder(digest))
    groups = await virlo_server.get_trends()
    assert groups["groups"][0]["trends"][0]["name"] == "AI agents"


# ---------------------------------------------------------------------------------------------
# 2. Bad arguments die here, not at Virlo (FR-119).
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "offender"),
    [
        ({"order_by": "engagement"}, "engagement"),  # the measured HTTP 400
        ({"order_by": "VIEWS"}, "VIEWS"),  # the enum is case-sensitive
        ({"sort": "descending"}, "descending"),
        ({"limit": 101}, "101"),  # one past Virlo's silent clamp
        ({"limit": 0}, "0"),
        ({"page": 0}, "0"),  # `page` is 1-indexed
    ],
)
async def test_invalid_arguments_are_refused_before_any_http_call(
    recorder: _Recorder, kwargs: dict[str, Any], offender: str
) -> None:
    with pytest.raises(MCPError) as caught:
        await virlo_server.get_top_videos(MONITOR, **kwargs)

    # Classified as the non-retryable caller-fault class, so no engine backoff repeats a doomed call.
    assert caught.value.code == ERROR_NOT_FOUND
    message = str(caught.value)
    assert offender in message
    assert next(iter(kwargs)) in message  # the message names the offending parameter...
    assert "allowed values are" in message  # ...and what it would have accepted
    assert recorder.calls == []  # nothing was spent finding out


async def test_limit_over_the_maximum_is_refused_not_clamped(recorder: _Recorder) -> None:
    """FR-285's rule: a typo is refused in one line. Virlo clamps 500 to 100 and says nothing."""
    with pytest.raises(MCPError) as caught:
        await virlo_server.get_top_slideshows(MONITOR, limit=500)

    assert "1 to 100" in str(caught.value)
    assert recorder.calls == []


async def test_a_bool_is_not_an_integer(recorder: _Recorder) -> None:
    """`bool` subclasses `int`, so an unguarded range check would accept `True` as `limit=1`."""
    with pytest.raises(MCPError) as caught:
        await virlo_server.get_top_videos(MONITOR, limit=True)

    assert caught.value.code == ERROR_NOT_FOUND
    assert recorder.calls == []


# ---------------------------------------------------------------------------------------------
# 3. `offset` is unsendable by construction, not by convention.
# ---------------------------------------------------------------------------------------------


async def test_offset_never_appears_on_any_request(recorder: _Recorder) -> None:
    """Every accepted shape of every media call, swept for the one parameter Virlo 400s on."""
    for kwargs in (
        {},
        {"limit": 100},
        {"limit": 100, "order_by": "views", "sort": "desc"},
        {"page": 3, "order_by": "created_at", "sort": "asc"},
    ):
        await virlo_server.get_top_videos(MONITOR, **kwargs)
        await virlo_server.get_top_slideshows(MONITOR, **kwargs)

    assert recorder.calls  # the sweep actually ran
    assert all("offset" not in params for params in recorder.sent_params)


async def test_get_refuses_an_unsupported_parameter_at_the_wire(recorder: _Recorder) -> None:
    """The allowlist sits in `_get`, so even a future in-module caller cannot smuggle `offset` out."""
    with pytest.raises(MCPError) as caught:
        await virlo_server._get(f"/agents/{MONITOR}/videos", {"limit": 10, "offset": 100})

    # Our bug rather than the caller's — no tool signature can produce it — so it is server-classed.
    assert caught.value.code == ERROR_SERVER
    assert "offset" in str(caught.value)
    assert recorder.calls == []
