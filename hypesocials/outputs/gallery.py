"""The run's one offline review page: `output/<run_id>/gallery.html` (FR-75/76/150/231, NFR-22).

Module contract
---------------
Purpose: turn a run folder into a single self-contained HTML page a human can judge in ~30
seconds — every creative next to the house-style references it was rendered from, its caption,
its identity badges, the receipt for the words it quoted, and its cost.
Public API: `write_gallery(run_dir, title=..., log=...) -> Path | None`.
Invariants:
- **Self-contained** (FR-75): CSS inlined in one `<style>`, media referenced by relative path,
  no CDN, no external font, no rating widget. It opens offline, from a USB stick, forever.
- **Incremental and idempotent** (FR-76): the page is rebuilt FROM DISK on every call, so the
  caller just calls it again whenever assets land; the write is temp+rename, so a browser tab
  refreshing mid-write never sees a truncated file.
- **Never blocks delivery** (NFR-22): any failure is caught, logged and returns `None` — the
  assets are on disk either way, and a template bug must not cost the operator a run.
- **One card per creative, in folder order** (D42/D43): A/B mode is dead, so there is no pairing,
  no pair badge and no row grouping — the ordinal in the asset id is the whole ordering. FR-231
  survives as the SELECTION artifact only (the header documents the marker file); its withdrawn
  half was the A/B integrity badge.
- **The judging question lives in the footer** (FR-150 as amended): style adherence + topical
  accuracy. Not fidelity to a trend's pixels — the run no longer has any.
- **The card answers "where did this come from"** (FR-76 as amended, FR-298): topic name, the
  assigned style key, the brand and whether this one was signed, the post it quoted and the
  exact ref label it quoted (`quotes P1.hook.2 verbatim`), and the source Virlo URL. Every one
  of those is a `meta.yaml` field written by `generate._record` — this module reads, never
  derives.
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
from typing import Any, Protocol
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

#: `copy_source_refs` slots in the order a human reads the creative (FR-298): the words that
#: became the biggest pixels first, the caption last. The first slot present is the one the
#: headline receipt quotes; the rest are listed after it. Slot names are `CopySet` field names,
#: set by `copywrite` when it resolves a ref to bytes.
_RECEIPT_SLOTS = ("headline", "overlay_text", "slide_1", "subline", "caption")


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
    cards = _load(run)
    delivered = sum(1 for _, meta in cards if meta.get("status") == "success")
    spend = sum(
        float(meta.get("actual_cost_usd") or meta.get("estimated_cost_usd") or 0.0)
        for _, meta in cards
    )
    body = "\n".join(_card_html(run, folder, meta) for folder, meta in cards)
    body = f'<div class="row">{body}</div>' if body else (
        '<p class="empty">No asset folders yet — this page refreshes as creatives land.</p>'
    )
    return _TEMPLATE.format(
        title=html.escape(title),
        run_id=html.escape(run.name),
        summary=f"delivered {delivered} of {len(cards)} · ${spend:.2f} spent",
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


def _card_html(run: Path, folder: Path, meta: _Meta) -> str:
    failed = meta.get("status") != "success"
    parts = [f'<article class="card{" failed" if failed else ""}">',
             f'<h2>{html.escape(folder.name)}</h2>',
             f'<div class="badges">{_badges(folder, meta)}</div>',
             _media_html(folder, meta),
             f'<div class="facts">{_facts(meta)}</div>']
    # The topic this creative is about (FR-76). `source_name` is the topic's own name, not the
    # monitor's; `topic_key` is its stable slug and stands in when a brief-driven creative or an
    # older meta has no name to show.
    topic = str(meta.get("source_name") or meta.get("topic_key") or "").strip()
    if topic:
        parts.append(f'<p class="prov">Topic: {html.escape(topic)}</p>')
    parts.extend(_receipt_html(meta))
    # The topic's own winning hook line, verbatim (`models.AssetRecord.source_hook`) — context for
    # the copy above it: this is what the trend sounded like, whether or not this creative quoted
    # that particular string.
    source_hook = str(meta.get("source_hook") or "").strip()
    if source_hook:
        parts.append(f'<p class="hook">Source hook: “{html.escape(source_hook)}”</p>')
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
        parts.append(f'<p class="src"><a href="{safe}">source topic on Virlo</a></p>')
    parts.append("</article>")
    return "".join(part for part in parts if part)


def _receipt_html(meta: _Meta) -> list[str]:
    """FR-298's verbatim receipt: WHICH post this creative quoted, and WHICH exact strings.

    One headline line naming the most visible quoted slot (`quotes P1.hook.2 verbatim as the
    headline`) plus, when more than one slot was quoted, a second line listing the rest — the ref
    labels are the same `P<n>.<kind>[.<i>]` grammar the copy call was offered, so a label on the
    card can be traced straight to the post roster in run.log. Silent when nothing was quoted
    (an override brief, or a copy degrade that shipped our own words): an empty receipt is the
    honest answer, and the `copy_degraded` badge is already saying why.
    """
    refs = meta.get("copy_source_refs")
    refs = {str(slot): str(label) for slot, label in refs.items()
            if str(label).strip()} if isinstance(refs, dict) else {}
    post_id = str(meta.get("copy_source_post_id") or "").strip()
    if not refs:
        return [f'<p class="prov">Quoted post: {html.escape(post_id)}</p>'] if post_id else []
    order = [slot for slot in _RECEIPT_SLOTS if slot in refs]
    order += [slot for slot in refs if slot not in order]  # slides 2..N and anything newer
    lead = order[0]
    line = f"Quotes {refs[lead]} verbatim as the {_slot_label(lead)}"
    if post_id:
        line += f" · post {post_id}"
    out = [f'<p class="prov">{html.escape(line)}</p>']
    if rest := order[1:]:
        also = " · ".join(f"{_slot_label(slot)} {refs[slot]}" for slot in rest)
        out.append(f'<p class="prov">Also quoted: {html.escape(also)}</p>')
    return out


def _slot_label(slot: str) -> str:
    """A `CopySet` field name as a human reads it: `overlay_text` → overlay, `slide_1` → slide 1."""
    return slot.removesuffix("_text").replace("_", " ")


def _badges(folder: Path, meta: _Meta) -> str:
    """Identity badges, then EVERY degradation tag, looped over the enum (FR-73's single source)."""
    labels = [str(meta.get("platform") or "?"), str(meta.get("creative_format") or "?")]
    # FR-76/FR-73's post-pivot identity: which house style rendered this, which brand system it
    # belongs to, and whether the branding rotation signed THIS one (FR-292 brands a deterministic
    # fraction, so "unsigned" is a normal outcome and is stated rather than left to be inferred
    # from an absent badge). `brief_override` is a style key like any other — it says the override
    # brief, not the registry, was the visual authority for this creative (M14).
    if style_key := str(meta.get("style_key") or "").strip():
        labels.append(f"style: {style_key}")
    if brand := str(meta.get("brand") or "").strip():
        labels.append(f"brand: {brand}")
        labels.append("signed" if meta.get("branded") else "unsigned")
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
    """The references this creative was rendered from — FR-150 judges adherence by comparison.

    Two stores, both shown: the run-level `refs/<style_key>/` folder holding the house-style
    images every creative on that style was given (post-pivot the store is keyed by STYLE, since
    the style is the visual authority and one style serves many topics), and the asset's own
    `refs/` holding an override brief's images (D26), which belong to this creative alone.
    """
    key = str(meta.get("style_key") or "").strip()
    # Registry keys are slug-shaped already, but `save_reference` slugifies before writing, so
    # both spellings are tried rather than silently showing no references. A creative with no
    # style key contributes no run-level path at all — `refs/` itself holds only folders, so an
    # empty key would scan the whole store and quietly find nothing.
    sources = [folder / REFS_DIR]
    if key:
        sources += [run / REFS_DIR / key, run / REFS_DIR / slugify(key)]
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
footer {{ border-top:1px solid var(--line); padding-top:14px; margin-top:22px; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:13px; margin:0 0 8px; font-weight:600; }}
.sub, .howto {{ color:var(--mut); font-size:13px; margin:4px 0 0; }}
code {{ background:var(--card); border:1px solid var(--line); border-radius:4px; padding:1px 5px; }}
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
.facts, .hook, .prov, .src {{ font-size:12px; color:var(--mut); margin:9px 0 0; }}
.prov {{ color:var(--fg); }}
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
<code>caption.txt</code> is the one file you may edit — publishing sends it verbatim.</p>
</header>
{body}
<footer>
<p class="howto">Rate this batch on <strong>style adherence</strong> and <strong>topical
accuracy</strong>: does each creative look like the house style shown in its references, and is
it about the topic and the post it quotes verbatim? Those two questions are the whole judgement
— fidelity to a trend's own pixels is no longer what these are made from.</p>
</footer>
</body></html>
"""
