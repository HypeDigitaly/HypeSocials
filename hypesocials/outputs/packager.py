"""Everything one creative leaves on disk: its folder, its bytes, its caption, its meta.yaml.

Module contract
---------------
Purpose: own the run folder, the per-asset folder and the whole `meta.yaml` lifecycle
(`pending` at folder creation → terminal by temp+rename, NFR-21), so no caller ever spells an
asset path, an asset id, a file name or a YAML key itself.
Public API: `create_run_folder()` · `AssetFolder` · `read_meta()` ·
`update_meta()` · `set_marker()` / `has_marker()` / `clear_marker()` · `save_reference()` ·
`close_downloads()` · `PackagingError`.
Invariants:
- **A folder never holds media without meta** (NFR-21): the folder and its `pending` meta.yaml
  are created together, before a single byte is downloaded, and every later write is atomic.
- `meta.yaml` is `AssetRecord` field for field (FR-73) in **dataclass field order**
  (`sort_keys=False`) — one schema, one ordering, no second registry of key names. That includes
  FR-109/OQ-4's `render_not_reproducible: true` (Kie exposes no seeds) and FR-98's
  `aspect_ratio_requested` / `native_size_rendered`.
- A failed creative keeps its paid artifacts: `skip()` writes `SKIP_REASON.txt` and a
  `status: failed` meta, it never deletes the folder (FR-74, 10 §10).
- `caption.txt` is FR-230's publishing contract *and the one hand-editable asset file*: caption
  body, one blank line, hashtag line. Operator edits after the run are honored — nothing here
  rewrites it later.
- Asset ids arrive on the record, never minted here: `plan.py` is FR-71's single producer (the
  ordinal is the entry's plan position, unique per run), so this module cannot diverge from the
  ids the plan, the copy calls and the budget already logged.
Do not: write `run.log` / `events.jsonl` / `trend_history.json` / `latest.txt` from here (they
belong to `logwriter.py` and `state.py`); rewrite `caption.txt` after packaging; assume a Kie
result URL still resolves in a later run (~24 h retention — download inside the run).
"""

from __future__ import annotations

import errno
from collections.abc import Sequence
from dataclasses import fields
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from hypesocials.models import AssetRecord, AssetStatus, DegradationTag
from hypesocials.util import atomic_write, read_text, slugify

META_FILE = "meta.yaml"
CAPTION_FILE = "caption.txt"
SKIP_REASON_FILE = "SKIP_REASON.txt"
REFS_DIR = "refs"
#: The FR-231 / 60 FR-211 selection + idempotency family — one suffix, four well-known names.
SELECTED_MARKER = "SELECTED.marker"
PUBLISH_ATTEMPTED_MARKER = "PUBLISH_ATTEMPTED.marker"
PUBLISHED_MARKER = "PUBLISHED.marker"
PUBLISH_LIST = "publish.txt"

_MEDIA_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".webm"})
_DOWNLOAD_TIMEOUT_S = 120.0
_OUT_OF_SPACE = frozenset({errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)})


class PackagingError(RuntimeError):
    """A packaging step that failed with a machine-readable `reason` for `skip_reason` (FR-74).

    `disk_full` is the one the caller must react to beyond the single creative: 10 §10 stops
    further downloads rather than thrashing a full disk.
    """

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


# --------------------------------------------------------------------------- run folder & ids

def create_run_folder(output_dir: str | Path, run_id: str) -> Path:
    """Create `output/<run_id>/` (plus its shared `refs/`) and return it — FR-70.

    Called at launch, before any API call: an aborted run still leaves a folder holding its logs.
    """
    run_dir = Path(output_dir) / run_id
    (run_dir / REFS_DIR).mkdir(parents=True, exist_ok=True)
    return run_dir


def save_reference(
    run_dir: str | Path,
    key: str,
    data: bytes,
    *,
    index: int,
    suffix: str = "",
) -> Path:
    """Store one reference image the run actually attached at `refs/<key>/image_<n><ext>` (FR-71).

    `key` is the **style key** the images belong to (post-pivot: the visual authority is the
    meta-style registry, so the comparison folder is keyed by style, not by topic — one folder
    per style, however many creatives rotated onto it). It is slugified for the folder name, and
    registry keys are slug-shaped already, so the folder reads as its style: `refs/hypelead-
    brand-card/image_1.png`. An override brief's own images are NOT stored here: they are copied
    into the asset's own `refs/` by `AssetFolder.add_reference()` (D26), because they belong to
    one creative rather than to a style every creative may draw on.

    The gallery shows these next to each creative so FR-150's judgement — style adherence and
    topical accuracy — can be made by comparison rather than from memory. Everything here is an
    image: the D23 video-reference chain is gone with the pivot, so there is no second `kind`.
    """
    folder = Path(run_dir) / REFS_DIR / slugify(key)
    return _write_bytes(folder / f"image_{int(index)}{suffix or '.jpg'}", data)


# --------------------------------------------------------------------------- asset folder

class AssetFolder:
    """One `output/<run_id>/<asset_id>/` and the record that mirrors its `meta.yaml`.

    Constructing it CREATES the folder and writes the `pending` meta (NFR-21) — a kill between
    a download and a metadata write must never leave media with no meta, because the gallery and
    the Phase 2 publisher both read it. Every later call rewrites the meta atomically, so the
    file on disk is always one whole state.
    """

    __slots__ = ("path", "record")

    def __init__(self, run_dir: str | Path, record: AssetRecord) -> None:
        self.record = record
        self.path = Path(run_dir) / record.asset_id
        self.path.mkdir(parents=True, exist_ok=True)
        self._flush()

    # ------------------------------------------------------------- content

    def write_caption(self, caption: str, hashtags: Sequence[str] = ()) -> Path:
        """FR-230's exact contract: caption body, one blank line, then the hashtag line."""
        tags = " ".join(
            tag if tag.startswith("#") else f"#{tag}"
            for tag in hashtags if str(tag).strip()
        )
        body = (caption or "").strip()
        return _write_bytes(
            self.path / CAPTION_FILE,
            (f"{body}\n\n{tags}\n" if tags else f"{body}\n").encode("utf-8"),
        )

    async def store_render(
        self,
        url: str,
        *,
        slide: int | None = None,
        seed_frame: bool = False,
    ) -> Path:
        """Download one finished render into this folder and return its path (FR-72).

        The caller says what the bytes ARE — a slide, a seed frame, or the creative itself — and
        this decides the file name: `slide_01.jpg` … , `seed_frame.jpg`, `reel.mp4`, `image.jpg`.
        Raises `PackagingError` with `download_failed` or `disk_full`; a failed store is a failed
        creative (`skip()`), never a half-written file.
        """
        return self.store_bytes(await _download(url), self.render_name(url, slide, seed_frame))

    def store_bytes(self, data: bytes, name: str) -> Path:
        """Place already-held bytes in this folder atomically (temp+rename, same volume)."""
        return _write_bytes(self.path / name, data)

    def add_reference(self, source: str | Path) -> Path:
        """Copy a brief's own reference image into `<asset_id>/refs/` (FR-71, D26 packaging)."""
        src = Path(source)
        try:
            return _write_bytes(self.path / REFS_DIR / src.name, src.read_bytes())
        except OSError as exc:
            raise _os_error("reference copy failed", exc) from exc

    def render_name(self, url: str, slide: int | None = None, seed_frame: bool = False) -> str:
        """The on-disk name this render gets — public so the gallery/tests never guess it."""
        ext = _extension(url)
        if seed_frame:
            return f"seed_frame{ext or '.jpg'}"
        if slide is not None:
            return f"slide_{int(slide):02d}{ext or '.jpg'}"
        if self.record.creative_format == "reel":
            return f"reel{ext or '.mp4'}"
        return f"image{ext or '.jpg'}"

    # ------------------------------------------------------------- lifecycle

    def update(self, **field_values: Any) -> AssetRecord:
        """Set record fields and rewrite `meta.yaml` atomically. Unknown names raise."""
        for name, value in field_values.items():
            if not hasattr(self.record, name):
                raise AttributeError(f"AssetRecord has no field {name!r}")
            setattr(self.record, name, value)
        self._flush()
        return self.record

    def finish(self, **field_values: Any) -> AssetRecord:
        """Terminal success: `status: success` plus whatever the render reported (NFR-21)."""
        return self.update(status=AssetStatus.SUCCESS, **field_values)

    def skip(
        self,
        reason: str,
        tag: DegradationTag | None = None,
        **field_values: Any,
    ) -> AssetRecord:
        """Terminal failure that KEEPS its paid artifacts (FR-74): SKIP_REASON.txt + failed meta.

        `reason` is one machine-readable line ("kie_timeout (job kie_xyz789)"); `tag` is the same
        cause in FR-73's vocabulary, appended to `degradations` so the gallery badges it.
        """
        line = " ".join(str(reason).split()) or "unknown"
        _write_bytes(self.path / SKIP_REASON_FILE, f"{line}\n".encode("utf-8"))
        if tag is not None and tag not in self.record.degradations:
            self.record.degradations.append(tag)
        return self.update(status=AssetStatus.FAILED, skip_reason=line, **field_values)

    def mark(self, tag: DegradationTag) -> AssetRecord:
        """Record one degradation without changing status — e.g. `refs_dropped_moderation`."""
        if tag not in self.record.degradations:
            self.record.degradations.append(tag)
            self._flush()
        return self.record

    def _flush(self) -> None:
        _write_bytes(self.path / META_FILE, _dump(_record_dict(self.record)).encode("utf-8"))


# --------------------------------------------------------------------------- meta & markers

def read_meta(asset_dir: str | Path) -> dict[str, Any]:
    """Parse an asset's `meta.yaml`, or `{}` — a missing/corrupt meta never raises at the reader.

    The gallery renders whatever it finds and the Phase 2 publisher skips what it cannot read;
    neither is allowed to die on one bad file in a folder of thirty.
    """
    try:
        loaded = yaml.safe_load(read_text(Path(asset_dir) / META_FILE))
    except (OSError, yaml.YAMLError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def update_meta(asset_dir: str | Path, **field_values: Any) -> dict[str, Any]:
    """Merge fields into an existing `meta.yaml` by temp+rename, preserving key order (FR-88).

    The path-based mutator: Phase 2 `publishing/` holds a folder, not an `AssetRecord`, and
    writes `postiz_draft_id` / `postiz_post_id` / `postiz_state` / `postiz_media_ids` through
    exactly this call. Known keys keep their FR-73 position; new keys append.
    """
    path = Path(asset_dir) / META_FILE
    data = read_meta(asset_dir)
    data.update({name: _plain(value) for name, value in field_values.items()})
    _write_bytes(path, _dump(data).encode("utf-8"))
    return data


def set_marker(asset_dir: str | Path, name: str = SELECTED_MARKER, content: str = "") -> Path:
    """Create one `.marker` file — the operator's `SELECTED.marker` (FR-231) and Phase 2's
    `PUBLISH_ATTEMPTED.marker` → `PUBLISHED.marker` intent record (60 FR-215) are one mechanism.
    """
    return _write_bytes(Path(asset_dir) / name, (content or "").encode("utf-8"))


def has_marker(asset_dir: str | Path, name: str = SELECTED_MARKER) -> bool:
    """True when that marker file exists — the gallery's selected badge, publish's filter."""
    return (Path(asset_dir) / name).is_file()


def clear_marker(asset_dir: str | Path, name: str = SELECTED_MARKER) -> None:
    """Remove a marker if present (`PUBLISH_ATTEMPTED` → `PUBLISHED` clears the first)."""
    (Path(asset_dir) / name).unlink(missing_ok=True)


# --------------------------------------------------------------------------- internals

def _record_dict(record: AssetRecord) -> dict[str, Any]:
    """`AssetRecord` → YAML-safe dict in dataclass field order (FR-73's grouping, verbatim)."""
    return {item.name: _plain(getattr(record, item.name)) for item in fields(record)}


def _plain(value: Any) -> Any:
    """Enums to their value, Paths to text — `yaml.safe_dump` refuses anything else."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    return value


def _dump(data: dict[str, Any]) -> str:
    """Deterministic YAML: declaration order, UTF-8 kept readable, no aliases, block style."""
    return yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100,
    )


def _write_bytes(path: Path, data: bytes) -> Path:
    try:
        atomic_write(path, data)
    except OSError as exc:
        raise _os_error(f"cannot write {path.name}", exc) from exc
    return path


def _os_error(message: str, exc: OSError) -> PackagingError:
    """Disk-full is its own reason: 10 §10 stops further downloads on it, not on any OSError."""
    reason = "disk_full" if exc.errno in _OUT_OF_SPACE else "write_failed"
    return PackagingError(f"{message}: {exc}", reason=reason)


def _extension(url: str) -> str:
    suffix = Path(urlparse(str(url)).path).suffix.lower()
    return suffix if suffix in _MEDIA_EXTS else ""


_http: httpx.AsyncClient | None = None


async def _download(url: str) -> bytes:
    """Fetch one finished render. Kie result URLs are same-run-only (~24 h), so this is where
    the bytes stop being a borrowed URL and start being the operator's file."""
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(
            timeout=httpx.Timeout(_DOWNLOAD_TIMEOUT_S, connect=15.0), follow_redirects=True,
        )
    try:
        response = await _http.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise PackagingError(f"download failed: {exc}", reason="download_failed") from exc
    if not response.content:
        raise PackagingError("download returned 0 bytes", reason="download_failed")
    return response.content


async def close_downloads() -> None:
    """Close the shared download client. Safe twice, called on every exit path (FR-249 posture)."""
    global _http
    client, _http = _http, None
    if client is not None:
        await client.aclose()
