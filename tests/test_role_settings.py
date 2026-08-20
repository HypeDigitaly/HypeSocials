"""F5 — which LLM role thinks how much, and what that turns into on the wire.

`runner._role_settings` is the ONE place a config row becomes an OpenRouter request parameter, and
`llm._build_body` is the one place that parameter becomes JSON. Session 5.5's F5 wired the critic
role through both, and this file pins the pair — the resolution and the request — because the
defect it closed was invisible at every other seam.

**What went wrong.** Critic requests set no `reasoning` field at all, and `runner._ROLE_EFFORT`
granted `reasoning_effort` to `copy` alone. An absent `reasoning` field is not "no thinking": a
thinking model left unbidden thinks at its own default effort, and Sonnet-5 bills those tokens
inside `completion_tokens`, where no per-role cap of ours can tell them from the answer. The
2026-08-14 acceptance run paid $1.30 in critic spend the pre-flight had never quoted, and hit three
truncation retries on top. The fix is one row of config, one entry in a map, and the two
assertions below.

**Offline by construction.** The request half uses `LLMClient(client=)` with a fake transport, so
no socket is opened and `api_key=""` is passed explicitly — no `OPENROUTER_API_KEY` is read and no
spend is possible. Only request BODIES are recorded, never headers, which is where the key lives
(D30).
"""

from __future__ import annotations

from typing import Any

from hypesocials.config import Config, CriticConfig
from hypesocials.llm import LLMClient
from hypesocials.runner import _live_roles, _role_settings

_SCHEMA = {"name": "gauntlet_brief", "schema": {"type": "object", "required": ["frames"],
                                                "properties": {"frames": {"type": "array"}}}}
_MESSAGES = [{"role": "system", "content": "judge these frames"},
             {"role": "user", "content": "go"}]


class _FakeResponse:
    """The four attributes `llm._post` reads — two on a 200, two on an error."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.status_code = 200
        self.headers: dict[str, str] = {}
        self.text = ""
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    """Stands in for `httpx.AsyncClient`, recording request bodies and nothing else."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    async def post(self, url: str, *, json: dict[str, Any],
                   headers: dict[str, str]) -> _FakeResponse:
        self.bodies.append(dict(json))
        return _FakeResponse({
            "choices": [{"message": {"content": '{"frames": []}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 18300, "completion_tokens": 5000, "cost": 0.09},
        })


# ------------------------------------------------------------------ the resolution (runner side)


def test_f5_the_critic_role_resolves_a_bounded_effort_and_analysis_resolves_none() -> None:
    """`_ROLE_EFFORT` is a map, and a role's ABSENCE from it is a decision with a price.

    `critic` is bounded at `low` because a defect report is a lookup against a contract, not a
    problem to reason through. `analysis` is deliberately still absent: its 12,000-token cap was
    sized around the unbidden reasoning it already bills (30 §2), so bounding it is a separate
    measurement rather than a free ride on this one — `None` here means "send no `reasoning` field",
    which is the expensive answer, chosen knowingly.
    """
    config = Config()

    assert _role_settings(config, "critic").reasoning_effort == "low"
    assert _role_settings(config, "analysis").reasoning_effort is None
    assert _role_settings(config, "copy").reasoning_effort == config.models.reasoning_effort


def test_f5_the_copy_and_critic_knobs_are_two_rows_that_never_move_each_other() -> None:
    """30 §2: two roles, two config keys. Raising the copywriter's effort must not re-open the
    critic's budget, and bounding the critic must not quieten the copywriter."""
    config = Config()
    config.models.reasoning_effort = "high"
    config.models.critic_reasoning_effort = "medium"

    assert _role_settings(config, "copy").reasoning_effort == "high"
    assert _role_settings(config, "critic").reasoning_effort == "medium"

    config.models.critic_reasoning_effort = "low"
    assert _role_settings(config, "copy").reasoning_effort == "high", "unchanged by its sibling"


def test_f5_a_per_critic_model_override_inherits_the_critic_roles_thinking_budget() -> None:
    """A `critic:<name>` role is the shared critic role with ONE field replaced — the model.

    A per-critic override exists so the cheap critic can be a cheap model; it is a choice of model
    and never a second budget, so its token cap, its floor and its reasoning effort are the critic
    role's. An override that quietly reverted to `None` here would restore the whole F5 defect for
    whichever critic an operator had bothered to tune.
    """
    config = Config()
    config.run.gauntlet.critics["craft"] = CriticConfig(model="anthropic/claude-haiku-4-5")

    craft = _role_settings(config, "critic:craft")

    assert "critic:craft" in _live_roles(config), "an override is only real once it is registered"
    assert craft.model == "anthropic/claude-haiku-4-5"
    assert craft.reasoning_effort == _role_settings(config, "critic").reasoning_effort == "low"
    assert craft.max_tokens == _role_settings(config, "critic").max_tokens


# --------------------------------------------------------------------- the request (llm.py side)


async def test_f5_a_critic_request_carries_reasoning_effort_low_on_the_wire() -> None:
    """The half that actually costs money: the resolved setting has to reach the request body.

    `reasoning: {effort: "low"}` is the field OpenRouter reads. Its absence is what let Sonnet-5
    think at full effort inside `completion_tokens` on every critic call of the 2026-08-14 run, so
    this asserts the JSON rather than the dataclass that produced it.
    """
    transport = _FakeClient()
    client = LLMClient({"critic": _role_settings(Config(), "critic")},
                       api_key="", client=transport)

    await client.structured_call("critic", _MESSAGES, _SCHEMA)

    assert len(transport.bodies) == 1
    assert transport.bodies[0]["reasoning"] == {"effort": "low"}
    assert "Authorization" not in transport.bodies[0], "the key never rides in a body (D30)"


async def test_f5_a_role_with_no_thinking_knob_sends_no_reasoning_field_at_all() -> None:
    """The other side of the map, asserted so "low everywhere" cannot land by accident.

    An empty `reasoning` object is not the same request as no `reasoning` key, and a role that has
    made no decision about its thinking budget must send the second one — that is what makes the
    omission visible in a captured payload rather than looking like a configured default.
    """
    transport = _FakeClient()
    client = LLMClient({"analysis": _role_settings(Config(), "analysis")},
                       api_key="", client=transport)

    await client.structured_call("analysis", _MESSAGES, _SCHEMA)

    assert "reasoning" not in transport.bodies[0]
