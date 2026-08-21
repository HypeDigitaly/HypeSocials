"""Outputs domain — everything a run writes to disk, and everything a later run reads back.

Callers import from `hypesocials.outputs` only, never from its modules (guidelines §3a/§18):

    LogWriter       the run's single serialized run.log + events.jsonl writer, with the
                    secret-redaction boundary inside it (FR-77–81, FR-152, NFR-23)
    Ledger          append-only outstanding-task ledger in the run folder (FR-203, FR-89)
    read_history    logs/trend_history.json, warn-and-start-fresh on corruption (FR-82/83)
    days_since_use  a trend's recency in days, for Select's window check (NFR-24)
    used_posts      per topic, the post ids QUOTED inside the window, for Collect (FR-153, NFR-24)
    record_use      lock-guarded, pruned, atomic history update — topic entry and the posts it
                    quoted, each with its URL (FR-298); False = went read-only (FR-82/153/254)
    set_latest      canonical output/latest.txt + best-effort latest/ junction (FR-254, NFR-20)
    resolve_latest  the newest run folder that packaged assets, or None (Phase 2 --publish)

Append-only list: T2.5 adds the packager and gallery exports here; existing names do not move.

    AssetFolder     one asset folder + its meta.yaml lifecycle, pending -> terminal (FR-72–74,
                    NFR-21); `finish()` / `skip()` / `block()` / `update()` / `mark()` /
                    `store_render()` / `write_gauntlet_report()`
    BLOCKED_FILE / GAUNTLET_REPORT_FILE
                    the two files a gate-refused creative leaves beside its artifacts (FR-325/328)
    create_run_folder   output/<run_id>/ (+ its shared refs/), made at launch (FR-70)
    save_reference  a brief's attached reference stored at refs/<brief_name>/image_1.png (FR-71
                    as amended by D46 — the style picture channel is excised, briefs only)
    read_meta / update_meta / set_marker / has_marker / clear_marker
                    path-based meta + marker mutators — also Phase 2 publishing's write path
                    (FR-88, FR-231, 60 FR-215)
    SELECTED_MARKER / PUBLISHED_MARKER / PUBLISH_ATTEMPTED_MARKER / PUBLISH_LIST
                    the selection + idempotency file names, spelled once
    close_downloads the shared asset-download client, closed on every exit path
    PackagingError  a failed store, carrying `disk_full` / `download_failed` for skip_reason
    write_gallery   self-contained incremental gallery.html; returns None instead of raising
                    (FR-75/76/150/231, NFR-22)

D65 (FR-365) adds the alpha-halo guard, the SECOND sanctioned Pillow use in the tree after
`sources/logo_crops.py`. Both entry points are SYNCHRONOUS and belong on a worker thread:

    inspect_frame   is this landed frame's edge ring see-through? -> AlphaVerdict (fail-open)
    flatten_frame   last resort: composite a haloed frame onto a ground sampled from itself
    AlphaVerdict / FlattenResult
                    the two frozen answers; `clean` and `ok` are the only fields a caller gates on

D65 (FR-370) adds the exact-pixel screenshot paste, the THIRD sanctioned Pillow use and the one
that composites: after a carousel slide lands, the source panel's own captured interface is cut
out of the already-downloaded source slide and written into the empty plate the render reserved.
LOCAL, POST-RENDER, OUTPUT-SIDE — it never uploads, never touches a render payload and imports
nothing from `render` or `generate`. Synchronous, like the two above, and belongs on a thread:

    paste_screenshot
                    composite one crop into one landed frame -> PasteResult (never raises)
    plate_zone      the reserved rectangle as prose, quoted by the prompt and by the contract
    PLATE / PLATES_DIR
                    the geometry both readers share, and the never-published backup folder
    PasteResult     the frozen answer; `ok` is the only field a caller gates on
"""

from hypesocials.outputs.logwriter import LogWriter
from hypesocials.outputs.state import (
    Ledger,
    days_since_use,
    read_history,
    record_use,
    resolve_latest,
    set_latest,
    used_posts,
)
from hypesocials.outputs.alpha_halo import (
    AlphaVerdict,
    FlattenResult,
    flatten_frame,
    inspect_frame,
)
from hypesocials.outputs.gallery import write_gallery
from hypesocials.outputs.screenshot_paste import (
    PLATE,
    PLATES_DIR,
    PasteResult,
    paste_screenshot,
    plate_zone,
    raw_backup_name,
)
from hypesocials.outputs.packager import (
    BLOCKED_FILE,
    GAUNTLET_REPORT_FILE,
    PUBLISH_ATTEMPTED_MARKER,
    PUBLISH_LIST,
    PUBLISHED_MARKER,
    SELECTED_MARKER,
    SOURCE_DIR,
    AssetFolder,
    PackagingError,
    clear_marker,
    close_downloads,
    create_run_folder,
    has_marker,
    read_gauntlet_report,
    read_meta,
    save_reference,
    set_marker,
    store_source,
    update_meta,
    write_source_yaml,
)

__all__ = [
    "AlphaVerdict",
    "FlattenResult",
    "flatten_frame",
    "inspect_frame",
    "PLATE",
    "PLATES_DIR",
    "PasteResult",
    "paste_screenshot",
    "plate_zone",
    "raw_backup_name",
    "LogWriter",
    "Ledger",
    "days_since_use",
    "read_history",
    "record_use",
    "resolve_latest",
    "set_latest",
    "used_posts",
    "AssetFolder",
    "BLOCKED_FILE",
    "GAUNTLET_REPORT_FILE",
    "PackagingError",
    "PUBLISHED_MARKER",
    "PUBLISH_ATTEMPTED_MARKER",
    "PUBLISH_LIST",
    "SOURCE_DIR",
    "store_source",
    "write_source_yaml",
    "SELECTED_MARKER",
    "clear_marker",
    "close_downloads",
    "create_run_folder",
    "has_marker",
    "read_gauntlet_report",
    "read_meta",
    "save_reference",
    "set_marker",
    "update_meta",
    "write_gallery",
]
