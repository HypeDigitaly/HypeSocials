"""SPIKE — RETIRED after Wave 1. Never imported by production code.

Child harness for the $0 Windows signal spike (T0.3 / spike F).

Proves the exact pattern the production runner must use (CLAUDE.md non-negotiable #2):
  * explicit ProactorEventLoop
  * asyncio.create_subprocess_exec works on it
  * signal.signal(SIGINT, handler) + loop.call_soon_threadsafe(...) to hand the
    signal to the loop  (loop.add_signal_handler is NOT available on Windows)
  * first SIGINT  -> graceful stop flag
  * second SIGINT -> hard stop (kill the child process tree, exit)

Modes:
  raise_signal  self-delivers SIGINT twice from a worker thread
  wait          just waits for an external CTRL_C_EVENT from the parent
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import threading
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

MODE = sys.argv[1] if len(sys.argv) > 1 else "wait"
T0 = time.monotonic()


def log(msg: str) -> None:
    print(f"[child t+{time.monotonic() - T0:5.2f}s] {msg}", flush=True)


async def amain() -> int:
    loop = asyncio.get_running_loop()
    log(f"loop={type(loop).__name__}")

    stop = asyncio.Event()
    hard = asyncio.Event()
    state = {"hits": 0}

    def on_stop() -> None:
        """Runs on the event loop thread (enqueued via call_soon_threadsafe)."""
        state["hits"] += 1
        if state["hits"] == 1:
            log("SIGINT #1 -> GRACEFUL flag set (finishing in-flight work)")
            stop.set()
        else:
            log(f"SIGINT #{state['hits']} -> HARD STOP")
            hard.set()

    def handler(signum, frame) -> None:  # noqa: ANN001, ARG001
        # Runs on the MAIN thread between bytecodes; must not touch loop state directly.
        loop.call_soon_threadsafe(on_stop)

    signal.signal(signal.SIGINT, handler)
    log("installed signal.signal(SIGINT, handler)")

    if MODE == "wait":
        # Popen created us with CREATE_NEW_PROCESS_GROUP, which DISABLES Ctrl+C for
        # this process. Re-enable it so GenerateConsoleCtrlEvent(CTRL_C_EVENT, pgid)
        # is actually delivered as SIGINT.
        import ctypes

        ok = ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False)
        log(f"SetConsoleCtrlHandler(NULL, FALSE) -> {ok} (0 = failed, no console?)")

    # Real subprocess on the Proactor loop: a sleeper we must reap on exit.
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(120)",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    log(f"spawned subprocess pid={proc.pid} via create_subprocess_exec")

    if MODE == "raise_signal":
        def raiser() -> None:
            time.sleep(2.0)
            log("thread: signal.raise_signal(SIGINT) #1")
            signal.raise_signal(signal.SIGINT)
            time.sleep(2.0)
            log("thread: signal.raise_signal(SIGINT) #2")
            signal.raise_signal(signal.SIGINT)

        threading.Thread(target=raiser, daemon=True).start()

    async def reap() -> None:
        """Kill the child subprocess, tolerating that it may ALREADY be dead.

        GOTCHA (proved by mechanism B): a real console Ctrl+C is delivered to the
        whole console process GROUP, so every subprocess we spawned (yt-dlp, MCP
        stdio servers) gets it too and may exit before we try to kill it.
        An unguarded proc.kill() then raises ProcessLookupError and takes the
        orderly-shutdown path down with it.
        """
        try:
            proc.kill()
        except ProcessLookupError:
            log("subprocess already dead (console-group Ctrl+C reached it too)")
        await proc.wait()
        log(f"subprocess reaped rc={proc.returncode}")

    try:
        await asyncio.wait_for(stop.wait(), timeout=20)
        log("graceful stop observed")
    except asyncio.TimeoutError:
        log("NO SIGINT observed within 20s — mechanism did NOT deliver")
        await reap()
        return 9

    try:
        await asyncio.wait_for(hard.wait(), timeout=20)
        log("hard stop observed")
    except asyncio.TimeoutError:
        log("second SIGINT NOT observed within 20s")
        await reap()
        return 8

    await reap()
    log("exiting 4 (Ctrl+C exit code)")
    return 4


def main() -> None:
    # Explicit, per CLAUDE.md rule #2 — do not rely on the platform default.
    loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(loop)
    try:
        rc = loop.run_until_complete(amain())
    finally:
        loop.close()
    sys.exit(rc)


if __name__ == "__main__":
    main()
