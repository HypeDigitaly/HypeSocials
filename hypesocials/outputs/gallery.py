"""The run's one offline review page: `output/<run_id>/gallery.html` (FR-75/76/150/231, NFR-22).

Module contract
---------------
Purpose: turn a run folder into a single self-contained HTML page a human can judge in ~30
seconds — every creative next to the source references it mimicked, its caption, its badges and
its cost.
Public API: `write_gallery(run_dir, title=..., log=...) -> Path | None`.
Invariants:
- **Self-contained** (FR-75): CSS inlined in one `<style>`, media referenced by relative path,
  no CDN, no external font, no rating widget. It opens offline, from a USB stick, forever.
- **Incremental and idempotent** (FR-76): the page is rebuilt FROM DISK on every call, so the
  caller just calls it again whenever assets land; the write is temp+rename, so a browser tab
  refreshing mid-write never sees a truncated file.
- **Never blocks delivery** (NFR-22): any failure is caught, logged and returns `None` — the
  assets are on disk either way, and a template bug must not cost the operator a run.
- **Badges come from `models.DegradationTag`**, looped (FR-73). A new tag needs no change here;
  a hardcoded badge list would be a second vocabulary and would rot on the first new tag.
- Reels use `<video preload="metadata">` with `seed_frame.*` as `poster` — the browser draws the
  first frame itself. No frame extraction, because that means ffmpeg, which this project does
  not carry (D10).
Do not: read `run.log`/`events.jsonl` (40 §4 owns those), fetch anything over the network, or
add grouping/toggle/ranking widgets — `gallery.title` is the ONLY gallery config key (FR-134).
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Iterable, Protocol
from urllib.parse import quote

from hypesocials.models import DegradationTag
from hypesocials.outputs.packager import (
    PUBLISH_LIST,
    REFS_DIR,
    SELECTED_MARKER,
    SKIP_REASON_FILE,
    has_marker,
    read_meta,
)
from hypesocials.util import atomic_write, read_text, slugify

GALLERY_FILE = "gallery.html"
_VIDEO_EXTS = frozenset({".mp4", ".mov", ".webm"})
_Meta = dict[str, Any]
_Card = tuple[Path, _Meta]


class _Log(Protocol):
    """The slice of `LogWriter` this module uses — passing one is optional."""

    def warn(self, event_type: str, message: str = "", **data: Any) -> str: ...


def write_gallery(
    run_dir: str | Path,
    *,
    title: str = "HypeSocials Run",
    log: _Log | None = None,
) -> Path | None:
    """Rebuild `gallery.html` from what is on disk right now. Returns the path, or None (NFR-22).

    Call it as often as you like: after the first images land, after every wave, at run end.
    Everything it needs — meta.yaml, caption.txt, the media files, `refs/` — is already written
    by `packager.py`, so there is no state to thread and no ordering to respect.
    """
    run = Path(run_dir)
    target = run / GALLERY_FILE
    try:
        atomic_write(target, _page(run, title))
        return target
    except Exception as exc:  # NFR-22: assets ship even when the page does not
        if log:
            log.warn("gallery_write_failed",
                     f"gallery.html not written; the assets are in {run}", detail=str(exc))
        return None


# --------------------------------------------------------------------------- page assembly

def _page(run: Path, title: str) -> str:
    groups = _grouped(_load(run))
    delivered = sum(1 for group in groups for _, meta in group if meta.get("status") == "success")
    total = sum(len(group) for group in groups)
    spend = sum(
        float(meta.get("actual_cost_usd") or meta.get("estimated_cost_usd") or 0.0)
        for group in groups for _, meta in group
    )
    body = "\n".join(_group_html(run, group) for group in groups) or (
        '<p class="empty">No asset folders yet — this page refreshes as creatives land.</p>'
    )
    return _TEMPLATE.format(
        title=html.escape(title),
        run_id=html.escape(run.name),
        summary=f"delivered {delivered} of {total} · ${spend:.2f} spent",
        selected=SELECTED_MARKER, publish_list=PUBLISH_LIST,
        body=body,
    )


def _load(run: Path) -> list[_Card]:
    """Every asset folder with a meta.yaml, in folder-name order (= plan order via the ordinal)."""
    cards: list[_Card] = []
    for folder in sorted(p for p in run.iterdir() if p.is_dir() and p.name != REFS_DIR):
        meta = read_meta(folder)
        if meta:
            cards.append((folder, meta))
    return cards


def _grouped(cards: Iterable[_Card]) -> list[list[_Card]]:
    """A/B siblings share one row, paired by `pair_id` — automatic, no config (FR-76/FR-22)."""
    groups: list[list[_Card]] = []
    pairs: dict[str, list[_Card]] = {}
    for card in cards:
        pair_id = str(card[1].get("pair_id") or "")
        if not pair_id:
            groups.append([card])
        elif pair_id in pairs:
            pairs[pair_id].append(card)
        else:
            pairs[pair_id] = [card]
            groups.append(pairs[pair_id])
    return groups


def _group_html(run: Path, group: list[_Card]) -> str:
    note = _pair_note(group)
    banner = f'<div class="pairnote">{html.escape(note)}</div>' if note else ""
    cards = "\n".join(_card_html(run, folder, meta) for folder, meta in group)
    return f'<section class="pair">{banner}<div class="row">{cards}</div></section>'


def _pair_note(group: list[_Card]) -> str:
    """FR-231's pair-integrity badge: a broken pair is labelled, never shown as a fair A/B."""
    if not group[0][1].get("pair_id"):
        return ""
    if any(DegradationTag.ANALYSIS_MISSING.value in _tags(meta) for _, meta in group):
        return "A/B invalid — analysis fell back to direct"
    if len(group) < 2 or any(meta.get("status") != "success" for _, meta in group):
        return "A/B pair incomplete — one variant did not ship"
    return "A/B pair — analyzed vs direct, same trend and copy"


def _card_html(run: Path, folder: Path, meta: _Meta) -> str:
    failed = meta.get("status") != "success"
    parts = [f'<article class="card{" failed" if failed else ""}">',
             f'<h2>{html.escape(folder.name)}</h2>',
             f'<div class="badges">{_badges(folder, meta)}</div>',
             _media_html(folder, meta),
             f'<div class="facts">{_facts(meta)}</div>']
    origin = " · ".join(str(meta.get(key) or "") for key in ("source_name", "hook_pattern_used"))
    if origin.strip(" ·"):
        parts.append(f'<p class="hook">{html.escape(origin.strip(" ·"))}</p>')
    # FR-76's source hook text, verbatim from the trend (models.AssetRecord.source_hook, v1.6.4) —
    # what the creative was mimicking, next to the pattern name it followed (FR-100/146).
    source_hook = str(meta.get("source_hook") or "").strip()
    if source_hook:
        parts.append(f'<p class="hook">Source hook: “{html.escape(source_hook)}”</p>')
    # A24: what our own analysis ASKED FOR — pattern · angle · palette
    # (`models.AssetRecord.style_brief_summary`). Next to the source hook above, the card now
    # carries all three sides of the judgement: what won, what we told the model to do about it,
    # and what came back. Absent in direct mode and after FR-12's degrade, where the
    # `analysis_missing` badge is already saying there was no brief.
    brief = str(meta.get("style_brief_summary") or "").strip()
    if brief:
        parts.append(f'<p class="hook">Brief asked for: {html.escape(brief)}</p>')
    skip = _text(folder / SKIP_REASON_FILE)
    if skip:
        parts.append(f'<p class="skip">Skipped: {html.escape(skip)}</p>')
    caption = _text(folder / "caption.txt")
    if caption:
        parts.append(f'<pre class="caption">{html.escape(caption)}</pre>')
    parts.append(_refs_html(run, folder, meta))
    url = str(meta.get("virlo_url") or "")
    if url:
        safe = html.escape(url, quote=True)
        parts.append(f'<p class="src"><a href="{safe}">source trend</a></p>')
    parts.append("</article>")
    return "".join(part for part in parts if part)


def _badges(folder: Path, meta: _Meta) -> str:
    """Identity badges, then EVERY degradation tag, looped over the enum (FR-73's single source)."""
    labels = [str(meta.get("platform") or "?"), str(meta.get("creative_format") or "?"),
              str(meta.get("variant") or "")]
    if meta.get("brief_name"):
        labels.append(f"brief: {meta['brief_name']}")
    labels.append(f"status: {meta.get('status', 'pending')}")
    vision = str(meta.get("vision_check_result") or "")
    if vision and vision != "not_checked":
        labels.append(f"vision: {vision}")
    if has_marker(folder, SELECTED_MARKER):
        labels.append("SELECTED")
    tags = _tags(meta)
    warn = [tag.value for tag in DegradationTag if tag.value in tags]
    warn += sorted(tags - {tag.value for tag in DegradationTag})  # unknown tag: shown, not hidden
    return "".join(
        f'<span class="badge">{html.escape(label)}</span>' for label in labels if label
    ) + "".join(
        f'<span class="badge warn">{html.escape(label.replace("_", " "))}</span>' for label in warn
    )


def _facts(meta: _Meta) -> str:
    ratio = str(meta.get("aspect_ratio_requested") or "?")
    native = str(meta.get("native_size_rendered") or "")
    bits = [
        f"est ${float(meta.get('estimated_cost_usd') or 0.0):.3f}",
        f"billed ${float(meta.get('actual_cost_usd') or 0.0):.3f}",
        f"ratio {ratio}" + (f" → {native}" if native and native != ratio else ""),
    ]
    models = meta.get("model_ids") or []
    if isinstance(models, list) and models:
        bits.append("models " + ", ".join(str(item) for item in models))
    if meta.get("slide_count"):
        missing = meta.get("missing_slide_numbers") or []
        bits.append(f"{meta['slide_count']} slides" + (f" (missing {missing})" if missing else ""))
    if meta.get("render_not_reproducible"):
        bits.append("not reproducible (no seed)")
    return " · ".join(html.escape(bit) for bit in bits)


def _media_html(folder: Path, meta: _Meta) -> str:
    poster = next(iter(sorted(folder.glob("seed_frame.*"))), None)
    files = (sorted(folder.glob("slide_*")) + sorted(folder.glob("image.*"))
             + sorted(folder.glob("reel.*")))
    if not files and poster:
        files = [poster]
    if not files:
        return '<div class="media empty">no media on disk</div>'
    poster_attr = f' poster="{_href(folder.name, poster.name)}"' if poster else ""
    tiles = []
    for item in files:
        src = _href(folder.name, item.name)
        if item.suffix.lower() in _VIDEO_EXTS:
            tiles.append(f'<video controls preload="metadata"{poster_attr} src="{src}"></video>')
        else:
            alt = html.escape(item.name)
            tiles.append(f'<a href="{src}"><img loading="lazy" src="{src}" alt="{alt}"></a>')
    return f'<div class="media">{"".join(tiles)}</div>'


def _refs_html(run: Path, folder: Path, meta: _Meta) -> str:
    """The source references this creative mimicked — FR-150 judges fidelity by comparison."""
    key = str(meta.get("source") or "")
    # The run-level store is keyed by the slugified trend key; `source` may still be the raw
    # agent id, so both spellings are tried rather than silently showing no references.
    sources = [folder / REFS_DIR, run / REFS_DIR / key, run / REFS_DIR / slugify(key)]
    tiles: list[str] = []
    for directory in dict.fromkeys(sources):
        if not directory.is_dir():
            continue
        rel = directory.relative_to(run).as_posix()
        for item in sorted(directory.iterdir()):
            if not item.is_file():
                continue
            src = "./" + quote(f"{rel}/{item.name}")
            tiles.append(
                f'<video controls preload="metadata" src="{src}"></video>'
                if item.suffix.lower() in _VIDEO_EXTS
                else f'<a href="{src}"><img loading="lazy" src="{src}" alt="reference"></a>'
            )
    return f'<div class="refs"><span>references</span>{"".join(tiles)}</div>' if tiles else ""


def _tags(meta: _Meta) -> set[str]:
    raw = meta.get("degradations") or []
    return {str(tag) for tag in raw} if isinstance(raw, list) else set()


def _text(path: Path) -> str:
    try:
        return read_text(path).strip()
    except OSError:
        return ""


def _href(*segments: str) -> str:
    return "./" + quote("/".join(segments))


#: ONE template string, per the pre-committed line-budget lever (plan §1a). Colours follow
#: `prefers-color-scheme` only — no toggle, no script, nothing to load (NFR-22, FR-75).
_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — {run_id}</title>
<style>
:root {{ color-scheme: light dark; --bg:#fff; --fg:#16181d; --mut:#5b6270; --line:#dfe3ea;
  --card:#fafbfc; --warn:#8a3b00; --warnbg:#ffe9d6; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14161a; --fg:#e9ecf1; --mut:#98a0ae;
  --line:#2a2f38; --card:#1b1e24; --warn:#ffcf9e; --warnbg:#43290f; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:24px; background:var(--bg); color:var(--fg); font:15px/1.5
  system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
header {{ border-bottom:1px solid var(--line); padding-bottom:14px; margin-bottom:20px; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:13px; margin:0 0 8px; font-weight:600; }}
.sub, .howto {{ color:var(--mut); font-size:13px; margin:4px 0 0; }}
code {{ background:var(--card); border:1px solid var(--line); border-radius:4px; padding:1px 5px; }}
.pair {{ margin:0 0 22px; }}
.pairnote {{ font-size:12px; color:var(--warn); background:var(--warnbg); border-radius:6px;
  padding:4px 9px; display:inline-block; margin-bottom:8px; }}
.row {{ display:flex; flex-wrap:wrap; gap:16px; align-items:flex-start; }}
.card {{ flex:1 1 380px; max-width:640px; background:var(--card); border:1px solid var(--line);
  border-radius:10px; padding:14px; }}
.card.failed {{ border-style:dashed; opacity:.85; }}
.badges {{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; }}
.badge {{ font-size:11px; border:1px solid var(--line); border-radius:999px; padding:2px 8px;
  color:var(--mut); }}
.badge.warn {{ color:var(--warn); background:var(--warnbg); border-color:transparent; }}
.media, .refs {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; }}
.media img, .media video {{ max-height:260px; max-width:100%; border-radius:8px; }}
.refs {{ margin-top:10px; padding-top:8px; border-top:1px dashed var(--line); }}
.refs img, .refs video {{ max-height:74px; border-radius:5px; }}
.refs span {{ font-size:11px; color:var(--mut); text-transform:uppercase; letter-spacing:.06em; }}
.facts, .hook, .src {{ font-size:12px; color:var(--mut); margin:9px 0 0; }}
.skip {{ font-size:12px; color:var(--warn); margin:9px 0 0; }}
.caption {{ white-space:pre-wrap; font:13px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace;
  background:var(--bg); border:1px solid var(--line); border-radius:8px; padding:10px;
  margin:10px 0 0; max-height:220px; overflow:auto; }}
.empty {{ color:var(--mut); }}
a {{ color:inherit; }}
</style></head>
<body>
<header>
<h1>{title}</h1>
<p class="sub">{run_id} · {summary}</p>
<p class="howto">To publish a subset: put an empty <code>{selected}</code> file in an asset
folder, or list asset ids (one per line) in <code>{publish_list}</code> next to this page.
With nothing selected, <code>--publish</code> sends every successfully packaged asset.
Judge fidelity by comparing each creative with the source references shown on its card;
<code>caption.txt</code> is the one file you may edit — publishing sends it verbatim.</p>
</header>
{body}
</body></html>
"""
