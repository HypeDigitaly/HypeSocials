"""The run's single serialized writer for `run.log` and `events.jsonl` (FR-77–81, 152, NFR-23).

Module contract
---------------
Purpose: one object owns both run-folder log files, their redaction boundary and their
verbosity split, so no other module ever opens either file.
Public API: `LogWriter(run_dir, secrets, verbose=...)` · `event()` · `warn()` · `error()` ·
`narrative()` · `close()` (also a context manager).
Invariants:
- **One writer per run.** Both files are opened once in append mode and stay open.
- **Serialized without a lock.** Every write is synchronous with NO `await` between building a
  line and flushing it, so the event loop's single thread interleaves nothing and no JSONL line
  can tear (FR-81, first of its two sanctioned designs). A buffered write plus `flush()` of a
  few hundred bytes is microseconds — accepted on the loop by FR-81's own design note, and it
  is what makes NFR-23's "flushed after every event" true when the run is killed mid-poll.
  Adding an `await` inside a write would silently reintroduce the tear.
- **Redaction is unconditional** (FR-152 / D30): Authorization-style header keys are masked
  wholesale and every configured secret VALUE becomes `[REDACTED]` wherever it appears — in the
  message, at any payload depth — before a byte is written. The secret set is never logged.
- **Full prompts and payloads go to `events.jsonl` only**; `run.log` gets a one-line digest
  (40 §4). Timestamps are FR-78 ISO-8601; durations are milliseconds.
Do not: write to run.log/events.jsonl from anywhere else; construct a second writer for a run;
pass secrets in through prompts (D30 — redaction here is the backstop, not the defense).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import TracebackType
from typing import Any, Iterable

from hypesocials.util import now_iso, open_utf8

#: Payload keys whose VALUE is credential material regardless of content. `request_token`,
#: `task_id` and friends deliberately do not match — the ledger's audit trail must stay readable.
_SECRET_KEYS = re.compile(
    r"(authorization|cookie|password|api[-_]?key|access[-_]?token|refresh[-_]?token"
    r"|client[-_]?secret|^secret$|_secret$)",
    re.IGNORECASE,
)
#: Keys that carry a full prompt / payload: events.jsonl keeps them, run.log gets a size note.
_FULL_ONLY_KEYS = frozenset(
    {"prompt", "prompts", "messages", "payload", "request", "response", "body",
     "raw", "raw_text", "schema", "json_schema", "images", "template"}
)
_REDACTED = "[REDACTED]"
_MIN_SECRET_LEN = 6  # shorter "secrets" would redact ordinary words out of the narrative
_DIGEST_VALUE_MAX = 120
_DIGEST_MESSAGE_MAX = 500


class LogWriter:
    """Writes one event to both run-folder logs at once — see the module contract above."""

    def __init__(
        self,
        run_dir: str | Path,
        secrets: Iterable[str] = (),
        *,
        verbose: bool = False,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        # Longest first, so a key that contains another key is masked whole.
        self._secrets = sorted(
            {s for s in secrets if isinstance(s, str) and len(s.strip()) >= _MIN_SECRET_LEN},
            key=len,
            reverse=True,
        )
        self._verbose = verbose
        self._log = open_utf8(self.run_dir / "run.log", "a")
        self._events = open_utf8(self.run_dir / "events.jsonl", "a")
        self._seq = 0

    # ----------------------------------------------------------------- public API

    def event(
        self,
        event_type: str,
        message: str = "",
        *,
        level: str = "info",
        duration_ms: int | None = None,
        verbose_only: bool = False,
        **data: Any,
    ) -> str:
        """Record one event in both files and return its `event_id` (meta.yaml's FR-73 pointer).

        `data` is the structured payload — full prompts, full API payloads, anything a future
        dashboard would parse (FR-80). It lands whole in events.jsonl and as a digest in
        run.log. `verbose_only=True` keeps the run.log line for `verbosity: verbose` runs only;
        events.jsonl always gets the event, because it is the machine record.
        """
        self._seq += 1
        stamp = now_iso()
        event_id = f"ev_{stamp[:10].replace('-', '')}_{self._seq:04d}"
        safe_message = self._redact(message)
        safe_data = self._redact(data)
        record: dict[str, Any] = {
            "event_id": event_id,
            "timestamp": stamp,
            "level": level,
            "event_type": event_type,
            "message": safe_message,
            "data": safe_data,
        }
        if duration_ms is not None:
            record["duration_ms"] = int(duration_ms)
        self._events.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._events.flush()  # NFR-23: the tail is truthful even if the next line kills us
        if self._verbose or not verbose_only:
            self._log.write(self._digest(stamp, level, event_type, safe_message,
                                         duration_ms, safe_data))
            self._log.flush()
        return event_id

    def warn(self, event_type: str, message: str = "", **data: Any) -> str:
        """Operational degradation the run survived (missing history, busy lock, dropped ref)."""
        return self.event(event_type, message, level="warn", **data)

    def error(self, event_type: str, message: str = "", **data: Any) -> str:
        """A failure that cost the operator something — a failed creative, an exhausted retry."""
        return self.event(event_type, message, level="error", **data)

    def narrative(self, text: str) -> str:
        """Append a pre-formatted block to run.log only — launch summary, FR-84 spend table.

        Redacted like everything else, written verbatim (no timestamp prefix) because these
        blocks are already laid out for a human. Returns the text as written, so a caller can
        print the identical block to the console without formatting it twice.
        """
        safe = self._redact(text)
        self._log.write(safe.rstrip("\n") + "\n")
        self._log.flush()
        return safe

    def close(self) -> None:
        """Flush and close both handles. Safe to call twice (every exit path calls it)."""
        for handle in (self._log, self._events):
            if not handle.closed:
                handle.flush()
                handle.close()

    def __enter__(self) -> LogWriter:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self.close()

    # ----------------------------------------------------------------- internals

    def _redact(self, value: Any) -> Any:
        """FR-152: mask credential-named keys, mask configured secret values at any depth.

        Bytes never reach a log as content — an image payload becomes a size note, which is all
        a reader could use anyway.
        """
        if isinstance(value, dict):
            return {
                key: (_REDACTED if _SECRET_KEYS.search(str(key)) else self._redact(item))
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [self._redact(item) for item in value]
        if isinstance(value, (bytes, bytearray)):
            return f"<{len(value)} bytes>"
        if isinstance(value, str):
            for secret in self._secrets:
                if secret in value:
                    value = value.replace(secret, _REDACTED)
            return value
        return value

    def _digest(self, stamp: str, level: str, event_type: str, message: str,
                duration_ms: int | None, data: dict[str, Any]) -> str:
        """One run.log line: `<iso> LEVEL event_type: message (342ms) k=v k=v` (FR-77/78).

        Prompt-sized values are named and sized, never inlined — 40 §4 puts them in
        events.jsonl exclusively.
        """
        parts = [f"{stamp} {level.upper():<5} {event_type}"]
        if message:
            parts.append(f": {_clip(message, _DIGEST_MESSAGE_MAX)}")
        if duration_ms is not None:
            parts.append(f" ({int(duration_ms)}ms)")
        for key, value in data.items():
            if key in _FULL_ONLY_KEYS:
                parts.append(f" {key}=<{len(str(value))} chars in events.jsonl>")
            else:
                parts.append(f" {key}={_clip(str(value).replace(chr(10), ' '), _DIGEST_VALUE_MAX)}")
        return "".join(parts) + "\n"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"
