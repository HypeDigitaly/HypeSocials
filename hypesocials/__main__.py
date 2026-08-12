"""`python -m hypesocials` — the process boundary: event loop, signals, action dispatch.

Module contract
---------------
Purpose: everything that must happen exactly once per process and cannot happen anywhere else —
force UTF-8 on the console (FR-256), sweep scratch a hard-killed predecessor left behind (FR-249),
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
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv

from hypesocials import cli, menu, previews, runner

#: Repo root — `.env` sits beside `run.bat`, never inside the package.
ROOT = Path(__file__).resolve().parent.parent

#: %TEMP% scratch left by PRE-PIVOT runs (the reference-download and video-reference chains,
#: both excised in W3.5 — nothing creates these folders any more). The sweep stays for one
#: release so a hard-killed pre-pivot run's leftovers still get cleaned; a day old cannot belong
#: to a live run, so nothing fresh is ever touched (FR-249).
_SCRATCH_GLOBS = ("hypesocials-refs-*", "hypesocials-videoref-*")
_SCRATCH_MAX_AGE_S = 24 * 60 * 60

_PHASE_2_NOTE = (
    "Publishing to Postiz is Phase 2 and is not implemented in the MVP.\n"
    "Review this run from its output folder; the full flow is specified in "
    "prds/60-publishing-postiz.md.\n"
    "Nothing was published and no billable call was made (FR-175)."
)


def main(argv: list[str] | None = None) -> int:
    """Parse, dispatch, and return the exit code. `run.bat` propagates it to Task Scheduler."""
    _force_utf8()
    _configure_logging()
    _sweep_stale_scratch()
    load_dotenv(ROOT / ".env")
    opts = cli.parse_args(argv)  # unknown flag: argparse exits 2 here, before any load (FR-63)
    config = None

    # The wizard is synchronous by contract and runs BEFORE the loop (30 §4, menu.py): it asks,
    # it never starts anything. Standalone actions never reach it, and `--yes` skips it (FR-60);
    # a run with no console falls through to `runner.run()`, which refuses per FR-66.
    if opts.action is cli.Action.RUN and opts.interactive and cli.console_refusal(opts) is None:
        result = menu.run_menu(opts)
        if result is None:  # quit at any step: nothing started, nothing spent (FR-59)
            return runner.EXIT_OK
        opts, config = result.options, result.config  # the Config carries the source pick, FR-135

    if opts.action in (cli.Action.PUBLISH, cli.Action.PROMOTE):
        print(_PHASE_2_NOTE)  # also the wizard's publish action (FR-175) — one honest message
        return runner.EXIT_OK

    loop = asyncio.ProactorEventLoop()  # explicit: subprocess support on Windows depends on it
    asyncio.set_event_loop(loop)
    control = runner.Control()
    _install_sigint(loop, control)
    try:
        if opts.action is cli.Action.LIST_MONITORS:
            return loop.run_until_complete(runner.list_monitors(opts))
        # Previews never prompt, so `console_refusal` must not gate them: headless
        # `--preview-sources` without `--yes` is legal (30 §5, FR-139/140).
        if opts.action is cli.Action.PREVIEW_SOURCES:
            return loop.run_until_complete(previews.preview_sources(opts, control))
        if opts.action is cli.Action.PREVIEW_ANALYSIS:
            return loop.run_until_complete(previews.preview_analysis(opts, control))
        return loop.run_until_complete(runner.run(opts, control, config=config))
    except KeyboardInterrupt:  # a press that landed outside the handler window
        return runner.EXIT_INTERRUPTED
    finally:
        _close(loop)


def _configure_logging() -> None:
    """FR-296/D45's one-time root-logger decision: stdlib logging never reaches the console.

    Unconfigured, `logging`'s last-resort handler leaked every module-level `logger.warning`
    bare onto stderr — undesigned output on a random channel, beside a console whose bytes are
    otherwise exactly run.log's (`session.say`). The sanctioned channels are `outputs.LogWriter`
    (run.log + events.jsonl, redaction inside) and the `say`/`note` seams; anything an operator
    must see is routed through those deliberately (the four virlo `_warn` sites do both). A
    `NullHandler` on the root terminates everything else silently — pytest's caplog still works,
    because pytest installs its own capturing handler above this one.
    """
    import logging

    logging.getLogger().addHandler(logging.NullHandler())


def _force_utf8() -> None:
    """FR-256: Czech survives a console `run.bat`'s `chcp 65001` never touched.

    A bare `python -m hypesocials`, a scheduled task or a redirected stdout all bypass the batch
    file, where one `ř` in a trend name would raise `UnicodeEncodeError`. `errors="replace"`
    because a mangled character is cosmetic; a crashed print mid-run is not.
    """
    for stream in (sys.stdout, sys.stderr):
        if reconfigure := getattr(stream, "reconfigure", None):
            reconfigure(encoding="utf-8", errors="replace")


def _sweep_stale_scratch() -> None:
    """Delete scratch folders an earlier hard-killed run left in %TEMP% (FR-249). Never raises."""
    cutoff = time.time() - _SCRATCH_MAX_AGE_S
    temp = Path(tempfile.gettempdir())
    for pattern in _SCRATCH_GLOBS:
        for folder in temp.glob(pattern):
            try:
                if folder.is_dir() and folder.stat().st_mtime < cutoff:
                    shutil.rmtree(folder, ignore_errors=True)
            except OSError:
                continue  # locked or already gone: the next run tries again


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
