"""Permit-gate tests — the W4 barrier item: wave-2 is never starved by queued wave-1 work.

Pure asyncio against `render.RenderGate`: no provider, no key, no network. That is the whole
reason the gate is constructible on its own (`render/__init__.py` public API note).

The gate exists because a plain `asyncio.Semaphore` is FIFO, and FIFO starves exactly the jobs
FR-106b forbids abandoning — carousel slides 2–N and the Seedance clip, whose prerequisites have
already been paid for. Every test below is that sentence, made checkable.
"""

from __future__ import annotations

import asyncio

import pytest

from hypesocials.render import RenderError, RenderGate
from hypesocials.models import RenderPriority

WAVE1, WAVE2 = RenderPriority.WAVE1, RenderPriority.WAVE2


class Gate:
    """A gate plus the bookkeeping every ordering assertion needs.

    `queue(name, priority)` starts one acquirer and lets it reach the gate; `served` is the order
    in which permits were actually granted; `finish(name)` lets that holder go.
    """

    def __init__(self, capacity: int) -> None:
        self.gate = RenderGate(capacity)
        self.served: list[str] = []
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self._releases: dict[str, asyncio.Event] = {}

    async def queue(self, name: str, priority: RenderPriority) -> None:
        release = self._releases[name] = asyncio.Event()

        async def hold() -> None:
            async with self.gate.permit(priority):
                self.served.append(name)
                await release.wait()

        self.tasks[name] = asyncio.create_task(hold(), name=name)
        await settle()

    async def finish(self, name: str) -> None:
        self._releases[name].set()
        await settle()

    async def drain(self) -> None:
        for name in list(self._releases):
            self._releases[name].set()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)


async def settle(ticks: int = 6) -> None:
    """Let every ready callback run, without introducing real time into an ordering test."""
    for _ in range(ticks):
        await asyncio.sleep(0)


async def test_permit_starvation_wave2_served_before_queued_wave1() -> None:
    """FR-25 / models.RenderPriority: "the allocator hands every released permit to a waiting
    WAVE2 acquirer before ANY queued WAVE1 acquirer, FIFO within each tier".

    The starvation shape, exactly: capacity is full of wave-1 work, three more wave-1 jobs are
    already queued, and only then does a pre-committed wave-2 job arrive. Under a plain semaphore
    it would wait behind all three; here it is served by the very first release.
    """
    gate = Gate(capacity=2)
    await gate.queue("held-a", WAVE1)
    await gate.queue("held-b", WAVE1)
    assert gate.served == ["held-a", "held-b"] and gate.gate.in_flight == 2

    for name in ("wave1-1", "wave1-2", "wave1-3"):
        await gate.queue(name, WAVE1)
    await gate.queue("wave2", WAVE2)  # arrives LAST, behind three queued wave-1 acquirers
    assert gate.served == ["held-a", "held-b"], "a full gate must not hand out a fourth permit"

    await gate.finish("held-a")
    assert gate.served[-1] == "wave2"  # last in, first served — the whole point of the gate
    assert gate.gate.in_flight == 2  # transferred, not double-counted

    await gate.finish("held-b")
    assert gate.served[-1] == "wave1-1"  # then FIFO inside the wave-1 tier
    await gate.finish("wave2")
    assert gate.served[-1] == "wave1-2"
    await gate.finish("wave1-1")
    assert gate.served == ["held-a", "held-b", "wave2", "wave1-1", "wave1-2", "wave1-3"]

    await gate.drain()
    assert gate.gate.in_flight == 0


async def test_permit_priority_never_preempts_a_held_permit() -> None:
    """"Priority applies to the QUEUE, never preempting a held permit" — a running job always
    finishes, because cancelling paid work is the one thing worse than waiting for it."""
    gate = Gate(capacity=1)
    await gate.queue("running-wave1", WAVE1)
    await gate.queue("waiting-wave2", WAVE2)

    await settle()
    assert gate.served == ["running-wave1"]  # the wave-2 arrival does not evict it
    assert not gate.tasks["running-wave1"].done()

    await gate.finish("running-wave1")
    assert gate.served == ["running-wave1", "waiting-wave2"]
    await gate.drain()


async def test_permit_fifo_within_a_tier_is_arrival_order() -> None:
    """Inside one tier the gate is plain FIFO — no reordering, no barging past a queued waiter."""
    gate = Gate(capacity=1)
    await gate.queue("holder", WAVE1)
    for name in ("first", "second", "third"):
        await gate.queue(name, WAVE1)

    await gate.finish("holder")
    await gate.finish("first")
    await gate.finish("second")
    assert gate.served == ["holder", "first", "second", "third"]
    await gate.drain()


async def test_cancelled_waiter_passes_a_delivered_permit_on_instead_of_losing_it() -> None:
    """`_acquire`'s documented cancellation path: a permit can be handed to a waiter in the same
    tick it is cancelled, and it must be passed on rather than leaked — a lost permit shrinks
    `max_inflight_render_jobs` for the rest of the run."""
    gate = Gate(capacity=1)
    await gate.queue("holder", WAVE1)
    await gate.queue("cancelled", WAVE1)
    await gate.queue("next", WAVE1)

    gate._releases["holder"].set()
    await asyncio.sleep(0)  # the holder releases; the permit is handed to `cancelled`
    gate.tasks["cancelled"].cancel()
    await settle()

    assert gate.served[-1] == "next", "the permit must reach the next waiter, not vanish"
    assert gate.gate.in_flight == 1
    await gate.drain()
    assert gate.gate.in_flight == 0


async def test_cancelled_queued_waiter_leaves_the_queue_cleanly() -> None:
    """A waiter cancelled while still queued removes itself, so no release is ever spent on a
    task that is no longer there."""
    gate = Gate(capacity=1)
    await gate.queue("holder", WAVE1)
    await gate.queue("gone", WAVE1)
    await gate.queue("survivor", WAVE1)

    gate.tasks["gone"].cancel()
    await settle()
    await gate.finish("holder")

    assert gate.served == ["holder", "survivor"]
    await gate.drain()
    assert gate.gate.in_flight == 0


def test_capacity_below_one_cannot_bound_anything() -> None:
    """`max_inflight_render_jobs` is a bound, and a bound of zero is a misconfiguration, not a
    pause button — it is refused where it is read, before any job is submitted."""
    with pytest.raises(RenderError):
        RenderGate(0)
