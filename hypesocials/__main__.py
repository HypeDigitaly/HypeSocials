"""`python -m hypesocials` — the process boundary: event loop, signals, action dispatch.

Module contract
---------------
Purpose: everything that must happen exactly once per process and cannot happen anywhere else —
load `.env`, build the Windows event loop, install the SIGINT handler, route the parsed action,
and return the FR-202 exit code to `run.bat`. No pipeline logic lives here.

Invariants:
- **`ProactorEventLoop`, explicitly** (plan §1). It is the Windows default on 3.8+, but stating
  it is what stops a future `asyncio.run()` refactor from silently losing subprocess support —
  and every MCP stdio server, `mklink /J` and `taskkill` call needs it.
- **SIGINT via `signal.signal` + `loop.call_soon_threadsafe`, never `loop.add_signal_handler`**,
  which raises `NotImplementedError` on Proactor — proven, not assumed (spikes/RESULTS.md §F).
  The handler runs on the MAIN thread between bytecodes and must not touch loop state directly.
- **Two stages** (FR-201): the first Ctrl+C sets the stop flag, so the runner stops ordering new
  work and still packages, writes the gallery, flushes the logs and exits `4`; the second exits
  at once. The immediate exit is safe precisely because every MCP subprocess belongs to a
  kill-on-close Windows job object (FR-111) — losing this process kills the tree.
- **Secrets enter the process here and only here** (D30): `.env` values become environment
  variables, which is the one place `mcp_client` and the REST seams read them from.

Do not: call `asyncio.run()` (it builds its own loop and discards ours), install a signal handler
on the loop, or put a stage here — `runner.py` owns the pipeline.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from hypesocials import cli, runner

#: Repo root — `.env` sits beside `run.bat`, never inside the package.
ROOT = Path(__file__).resolve().parent.parent

_PHASE_2_NOTE = (
    "Publishing to Postiz is Phase 2 and is not implemented in the MVP.\n"
    "Review this run from its output folder; the full flow is specified in "
    "prds/60-publishing-postiz.md.\n"
    "Nothing was published and no billable call was made (FR-175)."
)
_PREVIEW_NOTE = (
    "{flag} is built in Wave 5 (plan §2 T5.2) — it will replay this run's Collect/Select "
    "(and Analyze/Write) stages verbatim rather than a parallel dry-run path (D19).\n"
    "Nothing was spent."
)


def main(argv: list[str] | None = None) -> int:
    """Parse, dispatch, and return the exit code. `run.bat` propagates it to Task Scheduler."""
    load_dotenv(ROOT / ".env")
    opts = cli.parse_args(argv)  # unknown flag: argparse exits 2 here, before any load (FR-63)

    if opts.action in (cli.Action.PUBLISH, cli.Action.PROMOTE):
        print(_PHASE_2_NOTE)
        return runner.EXIT_OK
    if opts.action in (cli.Action.PREVIEW_SOURCES, cli.Action.PREVIEW_ANALYSIS):
        print(_PREVIEW_NOTE.format(flag=f"--{opts.action.value}"))
        return runner.EXIT_PREFLIGHT

    loop = asyncio.ProactorEventLoop()  # explicit: subprocess support on Windows depends on it
    asyncio.set_event_loop(loop)
    control = runner.Control()
    _install_sigint(loop, control)
    try:
        if opts.action is cli.Action.LIST_MONITORS:
            return loop.run_until_complete(runner.list_monitors(opts))
        return loop.run_until_complete(runner.run(opts, control))
    except KeyboardInterrupt:  # a press that landed outside the handler window
        return runner.EXIT_INTERRUPTED
    finally:
        _close(loop)


def _install_sigint(loop: asyncio.AbstractEventLoop, control: runner.Control) -> None:
    """The RESULTS.md §F pattern, verbatim: signal.signal + call_soon_threadsafe.

    `loop.add_signal_handler` raises `NotImplementedError` on a Proactor loop, so the handler
    runs on the main thread and does nothing but hand a callable to the loop. The second press
    leaves immediately: children die with the process because their job objects are kill-on-close
    (FR-111), which is exactly why `.kill()` is only belt-and-braces here.
    """
    hits = 0

    def on_stop() -> None:  # runs ON the loop thread
        control.stop.set()

    def handler(signum: int, frame: object) -> None:  # runs on the MAIN thread
        nonlocal hits
        hits += 1
        if hits == 1:
            print("\nCtrl+C — no new work will be ordered; packaging what already exists. "
                  "Press Ctrl+C again to quit at once (work already submitted is billed either "
                  "way).", flush=True)
            loop.call_soon_threadsafe(on_stop)
            return
        control.hard.set()
        print("\nCtrl+C again — exiting now; child processes go with this one.", flush=True)
        sys.stdout.flush()
        os._exit(runner.EXIT_INTERRUPTED)  # noqa: SLF001 — immediate by contract (FR-201)

    signal.signal(signal.SIGINT, handler)


def _close(loop: asyncio.AbstractEventLoop) -> None:
    """Cancel whatever is left, let it unwind once, and close the loop. Never raises."""
    try:
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
    except (RuntimeError, ProcessLookupError):
        pass  # a child already died with the console (RESULTS.md §F gotcha)
    finally:
        loop.close()


if __name__ == "__main__":
    raise SystemExit(main())
