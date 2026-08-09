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

    AssetFolder     one asset folder + its meta.yaml lifecycle, pending -> terminal (FR-72–74,
                    NFR-21); `finish()` / `skip()` / `update()` / `mark()` / `store_render()`
    create_run_folder   output/<run_id>/ (+ its shared refs/), made at launch (FR-70)
    save_reference  a used reference stored at refs/<trend>/image_1.jpg for the gallery (FR-71/150)
    read_meta / update_meta / set_marker / has_marker / clear_marker
                    path-based meta + marker mutators — also Phase 2 publishing's write path
                    (FR-88, FR-231, 60 FR-215)
    SELECTED_MARKER / PUBLISHED_MARKER / PUBLISH_ATTEMPTED_MARKER / PUBLISH_LIST
                    the selection + idempotency file names, spelled once
    close_downloads the shared asset-download client, closed on every exit path
    PackagingError  a failed store, carrying `disk_full` / `download_failed` for skip_reason
    write_gallery   self-contained incremental gallery.html; returns None instead of raising
                    (FR-75/76/150/231, NFR-22)
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
from hypesocials.outputs.gallery import write_gallery
from hypesocials.outputs.packager import (
    PUBLISH_ATTEMPTED_MARKER,
    PUBLISH_LIST,
    PUBLISHED_MARKER,
    SELECTED_MARKER,
    AssetFolder,
    PackagingError,
    clear_marker,
    close_downloads,
    create_run_folder,
    has_marker,
    read_meta,
    save_reference,
    set_marker,
    update_meta,
)

__all__ = [
    "LogWriter",
    "Ledger",
    "days_since_use",
    "read_history",
    "record_trends",
    "resolve_latest",
    "set_latest",
    "AssetFolder",
    "PackagingError",
    "PUBLISHED_MARKER",
    "PUBLISH_ATTEMPTED_MARKER",
    "PUBLISH_LIST",
    "SELECTED_MARKER",
    "clear_marker",
    "close_downloads",
    "create_run_folder",
    "has_marker",
    "read_meta",
    "save_reference",
    "set_marker",
    "update_meta",
    "write_gallery",
]
