"""Outputs domain — everything a run writes to disk, and everything a later run reads back.

Callers import from `hypesocials.outputs` only, never from its modules (guidelines §3a/§18):

    LogWriter       the run's single serialized run.log + events.jsonl writer, with the
                    secret-redaction boundary inside it (FR-77–81, FR-152, NFR-23)
    Ledger          append-only outstanding-task ledger in the run folder (FR-203, FR-89)
    read_history    logs/trend_history.json, warn-and-start-fresh on corruption (FR-82/83)
    days_since_use  a trend's recency in days, for Select's window check (NFR-24)
    record_trends   lock-guarded, pruned, atomic history update; False = went read-only (FR-254)
    set_latest      canonical output/latest.txt + best-effort latest/ junction (FR-254, NFR-20)
    resolve_latest  the newest run folder that packaged assets, or None (Phase 2 --publish)

Append-only list: T2.5 adds the packager and gallery exports here; existing names do not move.
"""

from hypesocials.outputs.logwriter import LogWriter
from hypesocials.outputs.state import (
    Ledger,
    days_since_use,
    read_history,
    record_trends,
    resolve_latest,
    set_latest,
)

__all__ = [
    "LogWriter",
    "Ledger",
    "days_since_use",
    "read_history",
    "record_trends",
    "resolve_latest",
    "set_latest",
]
