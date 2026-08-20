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
- **The judging question lives in the footer** (FR-150 as amended v2.1.0): style adherence,
  topical accuracy AND panel fidelity. Not fidelity to a reference image — nothing here was
  cloned from one.
- **The card answers "where did this come from"** (FR-76 as amended, FR-298): topic name, the
  assigned style key, the brand and whether this one was signed, the post it quoted and the
  exact ref label it quoted (`quotes P1.hook.2 verbatim`), and the source Virlo URL. Every one
  of those is a `meta.yaml` field written by `generate._record` — this module reads, never
  derives.
- **The style badge says WHICH algorithm chose that key** (FR-337, v2.4.0): `style: X ·
  matched/high` for a matched pick, `style: X · rotation` for the FR-291 baseline, and a
  wanted-archetype note on the cards where the matcher found nothing in the registry that fitted.
  `style_reason` and `style_wanted` are MODEL-authored prose that reaches this page, so they go
  through the same `html.escape` every other read-from-disk string here does — there is one
  escaping mechanism in this module and no card is entitled to a second one.
- **A panel-mapped carousel gets FR-309's three-part card** (v2.1.0): the source post's own
  provenance (author, reach, date, permalink, original caption), the SOURCE panel strip with each
  panel's extracted words and visual brief, and OUR slides laid against them BY INDEX, so slide
  *i* sits beside source panel *i* and a fidelity judgement is a glance rather than a memory
  exercise. The trigger is a non-empty `panel_map`; an override-brief carousel (§0.14d, empty
  map, null `source_post`) and every image and reel keep the single-card layout unchanged — the
  fallback IS today's card.
- **`meta.yaml` is the only file this module opens** (module contract): `source_post`,
  `panel_map`, `source_panel_count` and `degradations` are read as written. `source.yaml` in the
  source store is provenance for humans and for `sources/slide_intel`, never a second input here
  — two readers of one archive is two chances to disagree about what the run did.
- **Source panels are LOCAL relative paths** (FR-75 as amended): `./source/<post_id>/slide_NN.jpg`,
  written into `panel_map.source_image` upstream. Anything absolute, remote or traversing is
  dropped at `_relative()` rather than rendered — one hotlink and the page stops being offline.
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
    BLOCKED_FILE,
    PUBLISH_LIST,
    REFS_DIR,
    SELECTED_MARKER,
    SKIP_REASON_FILE,
    SOURCE_DIR,
    has_marker,
    read_meta,
)
from hypesocials.util import atomic_write, read_text

GALLERY_FILE = "gallery.html"
_VIDEO_EXTS = frozenset({".mp4", ".mov", ".webm"})
_Meta = dict[str, Any]
_Card = tuple[Path, _Meta]

#: Run-level folders that are NOT assets: the brief-reference store (FR-71) and the source-slide
#: store (FR-71 as amended v2.1.0 — `source/<post_id>/slide_NN.jpg` + `source.yaml`). Both live
#: beside the asset folders and neither holds a `meta.yaml`, so skipping them is a statement of
#: intent rather than an optimisation: a future store that DID hold one must not become a card.
_NOT_ASSETS = frozenset({REFS_DIR, SOURCE_DIR})

#: FR-73's `panels_truncated`, read as a string because that is what `meta.yaml` carries.
_TRUNCATED = DegradationTag.PANELS_TRUNCATED.value

#: `copy_source_refs` slots in the order a human reads the creative (FR-298): the words that
#: became the biggest pixels first, the caption last. The first slot present is the one the
#: headline receipt quotes; the rest are listed after it. Slot names are `CopySet` field names,
#: set by `copywrite` when it resolves a ref to bytes.
_RECEIPT_SLOTS = ("headline", "overlay_text", "slide_1", "subline", "caption")

#: FR-337's `style_origin` vocabulary, as the CARD annotates it. `rotation_fallback` deliberately
#: reads `rotation`: the pick on that card genuinely IS the FR-291 baseline, which is what this
#: annotation names, and the fact that the matcher never spoke is already on the same line as the
#: `style match degraded` badge (`generate._record` writes the tag, the badge loop prints it). An
#: origin this table does not know is printed VERBATIM rather than dropped — the same rule the
#: degradation badges follow, and the reason a meta.yaml from a newer engine still reads honestly.
_ORIGIN_LABELS = {"matched": "matched", "rotation": "rotation", "rotation_fallback": "rotation"}

#: FR-73's `copy_mode` value that means "these slides were COMPRESSED, not quoted" (D54/FR-331).
#: Read as a string because that is what `meta.yaml` carries, and compared rather than imported
#: from `copywrite` for the same reason every other value here is: this module reads a document
#: off disk — including documents written by older versions of this engine — and must never gain
#: an import edge to the module that produced it.
_COMPRESS_MODE = "compress"


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
    Everything it needs — meta.yaml, caption.txt, the media files, the asset's `refs/`, and the
    run-level `source/<post_id>/` slide store — is already on disk (written by `packager.py` and
    `sources/slide_intel`), so there is no state to thread and no ordering to respect.
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
    partial = sum(1 for _, meta in cards if _is_partial(meta))
    spend = sum(
        float(meta.get("actual_cost_usd") or meta.get("estimated_cost_usd") or 0.0)
        for _, meta in cards
    )
    body = "\n".join(_card_html(folder, meta) for folder, meta in cards)
    body = f'<div class="row">{body}</div>' if body else (
        '<p class="empty">No asset folders yet — this page refreshes as creatives land.</p>'
    )
    return _TEMPLATE.format(
        title=html.escape(title),
        run_id=html.escape(run.name),
        # FR-321: a deck that shipped short is counted inside `delivered` — it DID ship — and then
        # named, so the opening summary of the page an operator reviews cannot present "delivered
        # 6 of 6" over a deck that is missing a slide.
        summary=(f"delivered {delivered} of {len(cards)}"
                 + (f" ({partial} partial)" if partial else "")
                 + f" · ${spend:.2f} spent"),
        selected=SELECTED_MARKER, publish_list=PUBLISH_LIST,
        body=body,
    )


def _is_partial(meta: _Meta) -> bool:
    """FR-321: did this creative ship successfully but SHORT of the deck it was ordered to be?

    `status == "success"` with `slide_count < slides_ordered` — the pair `carousel.package()`
    writes. Both must be present: a meta with no `slides_ordered` was packaged before FR-321 and
    makes no claim either way, and inferring one from `missing_slide_numbers` here would be a
    second implementation of the same predicate, free to disagree with the spend table's.
    """
    if meta.get("status") != "success":
        return False
    try:
        delivered, ordered = int(meta.get("slide_count") or 0), int(meta.get("slides_ordered") or 0)
    except (TypeError, ValueError):
        return False
    return bool(ordered and delivered < ordered)


def _load(run: Path) -> list[_Card]:
    """Every asset folder with a meta.yaml, in folder-name order (= plan order via the ordinal)."""
    cards: list[_Card] = []
    for folder in sorted(p for p in run.iterdir() if p.is_dir() and p.name not in _NOT_ASSETS):
        meta = read_meta(folder)
        if meta:
            cards.append((folder, meta))
    return cards


def _card_html(folder: Path, meta: _Meta) -> str:
    """One creative's card: FR-309's three-part deck when it is panel-mapped, today's card else.

    The run folder is no longer a parameter: every path a card renders is now relative to the run
    root and derivable from the asset folder's own name, because the last thing that needed the
    run itself — the run-level style-reference store — died with the style channel (D46/F3).
    """
    # FR-325 (v2.2.0, D49): BLOCKED is its own card, not a failed one. A failed creative has
    # nothing to show; a blocked one is COMPLETE — every slide rendered, every dollar spent — and is
    # being withheld because the critic panel found a standing defect. Drawing it dashed-and-faded
    # like a failure would tell the operator the render did not happen, which is the one thing that
    # is not true about it, and it is precisely the card they most need to look at.
    blocked = meta.get("status") == "blocked"
    failed = not blocked and meta.get("status") != "success"
    rows = _panel_rows(meta)  # FR-309's routing signal: non-empty ⇒ this deck came from a deck
    parts = [f'<article class="card{" failed" if failed else ""}'
             f'{" blocked" if blocked else ""}">',
             f'<h2>{html.escape(folder.name)}</h2>',
             f'<div class="badges">{_badges(folder, meta)}</div>']
    # FR-337: the style badge above says WHICH style and which algorithm chose it; these two lines
    # say why, and what the matcher wished the registry had. They sit here — before either layout
    # branches — so an image, a reel and a panel-mapped deck all carry them in the same place,
    # directly under the badge they explain, and neither layout has to remember to print them.
    parts.extend(_style_html(meta))
    parts.extend(_deck_html(folder, meta, rows) if rows else _single_html(folder, meta))
    # The topic's own winning hook line, verbatim (`models.AssetRecord.source_hook`) — context for
    # the copy above it: this is what the trend sounded like, whether or not this creative quoted
    # that particular string.
    source_hook = str(meta.get("source_hook") or "").strip()
    if source_hook:
        parts.append(f'<p class="hook">Source hook: “{html.escape(source_hook)}”</p>')
    if blocked_text := _text(folder / BLOCKED_FILE):
        # The whole plain-language paragraph, not a one-liner: it is the only place that says the
        # artifacts were kept, that the source post was not burnt, and where to read the defects.
        parts.append(f'<pre class="blocked">{html.escape(blocked_text)}</pre>')
    skip = _text(folder / SKIP_REASON_FILE)
    if skip and not blocked:  # a blocked card already carries the fuller explanation above
        parts.append(f'<p class="skip">Skipped: {html.escape(skip)}</p>')
    caption = _text(folder / "caption.txt")
    if caption:
        parts.append(f'<pre class="caption">{html.escape(caption)}</pre>')
    parts.append(_refs_html(folder))
    url = str(meta.get("virlo_url") or "")
    if url:
        safe = html.escape(url, quote=True)
        parts.append(f'<p class="src"><a href="{safe}">source topic on Virlo</a></p>')
    parts.append("</article>")
    return "".join(part for part in parts if part)


def _single_html(folder: Path, meta: _Meta) -> list[str]:
    """The card body every image, reel and override-brief carousel keeps (FR-309's fallback).

    Byte-for-byte the pre-D46 order — preview, facts, topic, receipt — because "the fallback IS
    the current card" is the requirement, not a summary of it.
    """
    parts = [_media_html(folder, meta), f'<div class="facts">{_facts(meta)}</div>']
    parts.extend(_topic_html(meta))
    parts.extend(_receipt_html(meta))
    return parts


def _deck_html(folder: Path, meta: _Meta, rows: list[dict[str, Any]]) -> list[str]:
    """FR-309's three parts, in its own order: provenance header, source strip, our slides.

    The header comes first because it answers the question the strip below it raises ("whose
    slides am I looking at?"), and the verbatim receipt (FR-298) belongs inside it: the ref labels
    it names — `P1.panel.3` — are labels ON the panels the strip is showing.
    """
    parts = [_provenance_html(meta)]
    parts.extend(_receipt_html(meta))
    parts.append(_panels_html(folder, meta, rows))
    parts.append(f'<div class="facts">{_facts(meta)}</div>')
    parts.extend(_topic_html(meta))
    return parts


def _topic_html(meta: _Meta) -> list[str]:
    """The topic this creative is about (FR-76). `source_name` is the topic's own name, not the
    monitor's; `topic_key` is its stable slug and stands in when a brief-driven creative or an
    older meta has no name to show."""
    topic = str(meta.get("source_name") or meta.get("topic_key") or "").strip()
    return [f'<p class="prov">Topic: {html.escape(topic)}</p>'] if topic else []


# ------------------------------------------------------------------ FR-309: the provenance card


def _panel_rows(meta: _Meta) -> list[dict[str, Any]]:
    """`panel_map`'s rows, or `[]` — the one signal that routes a card to FR-309's layout.

    Empty is a DECLARED shape, not missing data: an override-brief carousel binds no source post
    (§0.14d) and nothing that is not a deck has panels at all. A malformed row (anything that is
    not a mapping) is dropped rather than crashing the page — NFR-22 pays for a template error
    with the whole gallery, and one bad row is not worth that.
    """
    raw = meta.get("panel_map")
    return [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []


def _provenance_html(meta: _Meta) -> str:
    """FR-309 part 1 — whose deck this is: author, reach, date, post id, permalink, caption.

    Read straight off `meta.yaml`'s nested `source_post`, field by field, and every field is
    optional: a post the run bound but could no longer resolve carries its id alone, and printing
    the id alone is the honest rendering of that. The permalink is a LINK, never an embed — FR-75
    bans loading a remote byte, not naming where the deck lives.

    On a COMPRESSED deck (FR-309 as amended v2.3.0, D54) the header gains one more line, and it is
    the first thing an operator needs to know about this card: the words on our slides are not this
    post's words. The measure is the LONGEST `source_text_original` on the map — the biggest panel
    the copy model had to write down — because that is the number that says how far the compression
    had to travel, and an average would hide the 1,048-character panel that is the reason the mode
    exists.
    """
    post = meta.get("source_post")
    if not isinstance(post, dict) or not post:
        return ""
    facts: list[str] = []
    if author := str(post.get("author") or "").strip():
        facts.append(author if author.startswith("@") else f"@{author}")
    if views := _int(post.get("views")):
        facts.append(f"{views:,} views")
    if published := str(post.get("published_at") or "").strip():
        facts.append(published)
    if post_id := str(post.get("post_id") or "").strip():
        facts.append(f"post {post_id}")
    parts = [f'<p class="prov">Source deck: {html.escape(" · ".join(facts))}</p>'] if facts else []
    if url := str(post.get("url") or "").strip():
        parts.append(f'<p class="src"><a href="{html.escape(url, quote=True)}">'
                     "the original post</a></p>")
    if longest := _compressed_from(meta):
        parts.append(f'<p class="prov">Copy: compressed from {longest} chars — our slides are '
                     "this deck's panels compressed to the style's budget, never quoted (D54)</p>")
    if caption := " ".join(str(post.get("caption") or "").split()):
        # The creator's OWN caption, in its own language. Long by nature, so it is clamped by CSS
        # (scrollable, not cut): a truncated caption would look like a quote we shortened.
        parts.append(f'<p class="ocaption">Original caption: “{html.escape(caption)}”</p>')
    return f'<div class="head">{"".join(parts)}</div>' if parts else ""


def _compressed_from(meta: _Meta) -> int:
    """The LONGEST `source_text_original` on a compressed deck's map, else 0 (FR-309, v2.3.0).

    Zero on every verbatim deck, on every pre-D54 `meta.yaml` (no `copy_mode` key at all), and on a
    compressed deck whose rows somehow carry no original text — three different documents that all
    mean "there is no compression to label here", and all three must render exactly as they did
    before this function existed. `_row_original` does the per-row reading, so the header measure
    and the per-tile measure can never disagree about what counts as an original.
    """
    if str(meta.get("copy_mode") or "").strip() != _COMPRESS_MODE:
        return 0
    return max((_row_original(row) for row in _panel_rows(meta)), default=0)


def _row_original(row: dict[str, Any]) -> int:
    """How many characters of source panel THIS row's shipped text was compressed from, else 0.

    Both conditions are required and neither is redundant. `compressed` is the row's own claim (a
    verbatim row on a compressed deck's map is not a shape this engine writes, but a reader that
    trusted the deck-level mode would mislabel one if it ever appeared), and a non-empty original
    is what makes the number meaningful — a dropped panel has an empty `source_text_original` on
    some paths, and "compressed from 0 chars" is a sentence nobody should ever read. Tolerant by
    contract (NFR-22): a row with no `compressed` key is a pre-D54 row and answers 0.
    """
    if not row.get("compressed"):
        return 0
    return len(str(row.get("source_text_original") or ""))


def _panels_html(folder: Path, meta: _Meta, rows: list[dict[str, Any]]) -> str:
    """FR-309 parts 2+3 — one tile PER PANEL: their slide above, ours below, index stated.

    Pairing beats two independent strips here: two rows only line up while both are full, and the
    first missing source image or undelivered slide would shift one of them by a tile and turn the
    page into a lie that looks tidy. A pair holds its own alignment — a gap stays a gap, labelled
    `slide i ← source panel j` on the tile itself, so the mapping never has to be counted.
    """
    ours = _our_slides(folder)
    used: set[str] = set()
    tiles = []
    for row in rows:
        slide = _int(row.get("slide"))
        position = _int(row.get("source_position"))
        pin = f"slide {slide or '?'} ← source panel {position or '?'}"
        tiles.append(f'<div class="pair"><div class="pin">{html.escape(pin)}</div>'
                     f'{_source_side(row)}{_our_side(folder, ours.get(slide), used)}</div>')
    # Anything the deck delivered that no row claimed (a stray slide, an older meta) still shows:
    # media on disk is never hidden by a mapping that did not mention it.
    return (f'<div class="pairs">{"".join(tiles)}</div>{_panel_note(meta, rows)}'
            f'{_media_html(folder, meta, exclude=frozenset(used))}')


def _source_side(row: dict[str, Any]) -> str:
    """One SOURCE panel: its picture (local copy), its extracted words, its visual brief.

    The chip above the picture carries whichever provenance this row HAS. On a verbatim row that is
    the ref label the words were quoted under (`source · P1.panel.3`); on a D54-compressed row
    there is no label to name — FR-302 as amended gives compressed slides none — so it carries the
    compression instead (`source · compressed from 1048 chars`, FR-309 as amended v2.3.0). One
    chip, one slot, no new CSS: the label was always "how did this row's text come to be", and
    compression is a second answer to that question rather than a second question.

    `source_text` stays what it has always been — the string that SHIPPED — so the tile still shows
    the words that are burned into our slide beside the picture they came from. Under compression
    those are the compressed words, which is exactly what the chip has just said.
    """
    src = _relative(row.get("source_image"))
    label = str(row.get("ref_label") or "").strip()
    if compressed_from := _row_original(row):
        label = f"compressed from {compressed_from} chars"
    text = " ".join(str(row.get("source_text") or "").split())
    brief = " ".join(str(row.get("visual_brief") or "").split())
    parts = [f'<span class="tag">source{f" · {html.escape(label)}" if label else ""}</span>']
    parts.append(f'<a href="{src}"><img loading="lazy" src="{src}" alt="source panel"></a>'
                 if src else '<div class="gap">source slide not downloaded</div>')
    parts.append(f'<p class="ptext">“{html.escape(text)}”</p>' if text else
                 '<p class="ptext none">no words on this panel</p>')
    if brief:
        parts.append(f'<p class="brief">{html.escape(brief)}</p>')
    return f'<div class="side">{"".join(parts)}</div>'


def _our_side(folder: Path, item: Path | None, used: set[str]) -> str:
    """OUR slide for that same index, or a stated gap when it never landed (FR-20/95)."""
    if item is None:
        return ('<div class="side"><span class="tag">ours</span>'
                '<div class="gap">slide not delivered</div></div>')
    used.add(item.name)
    src = _href(folder.name, item.name)
    return (f'<div class="side"><span class="tag">ours</span>'
            f'<a href="{src}"><img loading="lazy" src="{src}" alt="{html.escape(item.name)}">'
            "</a></div>")


def _panel_note(meta: _Meta, rows: list[dict[str, Any]]) -> str:
    """The truncation sentence — the operator must not have to count tiles to notice a cut.

    `panels_truncated` (FR-304/§0.4′) means the tail was never ORDERED; a shorter deck without
    that tag means something else took the slides away. Both are stated, and neither is inferred
    from the other, because "we chose not to render panels 6–9" and "panels 6–9 failed" are
    different facts about the same-looking page.
    """
    total, shown = _int(meta.get("source_panel_count")), len(rows)
    if total <= shown:
        return ""
    line = (f"Showing the first {shown} of {total} source panels — the tail was never ordered "
            f"(panels_truncated), not lost in rendering." if _TRUNCATED in _tags(meta) else
            f"Our {shown} slide(s) against the source deck's {total} panels.")
    return f'<p class="note">{html.escape(line)}</p>'


def _our_slides(folder: Path) -> dict[int, Path]:
    """`{slide number: file}` for the deck we delivered — `slide_03.jpg` is slide 3 (FR-72).

    Parsed from the name rather than counted from a sorted list, so a deck missing slide 2 puts
    slide 3 against source panel 3 instead of sliding the whole tail up by one.
    """
    found: dict[int, Path] = {}
    for item in sorted(folder.glob("slide_*")):
        digits = "".join(char for char in item.stem.removeprefix("slide_") if char.isdigit())
        if digits:
            found.setdefault(int(digits), item)
    return found


def _relative(value: Any) -> str:
    """A run-relative media href, or `""` — FR-75's hotlink ban enforced at the last step.

    `panel_map.source_image` is written upstream as `source/<post_id>/slide_NN.jpg`, already
    relative to the run folder and forward-slashed. Anything else — an absolute URL, an absolute
    path, a traversal, a drive letter — is DROPPED rather than rendered: one remote byte and the
    page stops being the offline artifact FR-75 promises, and the tile degrades to exactly the
    gap a failed download already leaves.
    """
    text = str(value or "").strip().replace("\\", "/")
    if (not text or "://" in text or text.startswith("/")
            or ".." in text.split("/") or ":" in text.split("/")[0]):
        return ""
    return _href(text)


def _int(value: Any) -> int:
    """A meta.yaml number as an int; anything unreadable is 0, never an exception (NFR-22)."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _receipt_html(meta: _Meta) -> list[str]:
    """FR-298's verbatim receipt: WHICH post this creative quoted, and WHICH exact strings.

    One headline line naming the most visible quoted slot (`quotes P1.hook.2 verbatim as the
    headline`) plus, when more than one slot was quoted, a second line listing the rest — the ref
    labels are the same `P<n>.<kind>[.<i>]` grammar the copy call was offered, so a label on the
    card can be traced straight to the post roster in run.log. Silent when nothing was quoted
    (an override brief, or a copy degrade that shipped our own words): an empty receipt is the
    honest answer, and the `copy_degraded` badge is already saying why.

    **A COMPRESSED deck is answered first and separately (D54/FR-302 as amended).** It reaches here
    with a bound post id and an EMPTY `copy_source_refs`, which is precisely the shape the "nothing
    was quoted" branch below was built for — and that branch would print "Quoted post: <id>" over a
    deck that quoted nothing from it. The claim on this card is the post the words were compressed
    FROM, and the receipt for which words is the panel map, one row per slide, further down the
    card. Checked before the refs branch rather than inside it so the mode can never fall through
    to a "Quotes … verbatim" line either.
    """
    refs = meta.get("copy_source_refs")
    refs = {str(slot): str(label) for slot, label in refs.items()
            if str(label).strip()} if isinstance(refs, dict) else {}
    post_id = str(meta.get("copy_source_post_id") or "").strip()
    if str(meta.get("copy_mode") or "").strip() == _COMPRESS_MODE:
        return [f'<p class="prov">Compressed from post: {html.escape(post_id)} — see the panel '
                "map below for what each slide was compressed from</p>"] if post_id else []
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


# ------------------------------------------------------------------ FR-337: the style-match badge


def _style_label(meta: _Meta) -> str:
    """FR-337's style badge: which house style rendered this, and WHICH algorithm chose it.

    Three shapes, and the difference between them is a fact about the run rather than a formatting
    preference:

    * `style: quiet-luxury-night-photoreal · matched/high` — the D56 matcher read this creative's
      source and picked this style for it, with the fit it claimed. `medium` is a pick that was
      ACCEPTED (a decent fit is a fit), so it prints exactly like `high` does and the operator reads
      the difference rather than being told one of them is a problem.
    * `style: letterpress-print-carousel-teal · rotation` — the FR-291 deterministic baseline stood,
      either because the run is in rotation mode or because the matcher's answer for this entry was
      low, invalid or absent. A whole-call failure (`rotation_fallback`) reads the same way here and
      wears the `style match degraded` badge beside it, because the PICK is identical in both cases:
      annotating it differently would suggest a different style was rendered.
    * `style: brief_override` — no origin at all. Every `meta.yaml` written before v2.4.0 lands
      here too, and a page that reads a two-week-old run must not start printing an origin nobody
      recorded. The bare label is what those cards have always shown.

    A `low` fit keeps its number (`rotation/low`): that entry DID get an answer, the answer was
    "nothing here fits", and the wanted-archetype note under the badge is the other half of it.
    """
    key = str(meta.get("style_key") or "").strip()
    if not key:
        return ""
    origin = str(meta.get("style_origin") or "").strip()
    if not origin:
        return f"style: {key}"
    fit = str(meta.get("style_fit") or "").strip()
    return f"style: {key} · {_ORIGIN_LABELS.get(origin, origin)}" + (f"/{fit}" if fit else "")


def _style_html(meta: _Meta) -> list[str]:
    """FR-337's two style-match lines under the badges: the matcher's reason, then the gap it found.

    Both are MODEL-AUTHORED strings (`style_match`'s answer, straight through `PlanEntry` and
    `meta.yaml`), so both go through `html.escape` like every other string this module reads off
    disk, and both are whitespace-collapsed first — a reason that arrived with a newline in it
    would otherwise open a two-line hole in a one-line slot.

    The wanted-archetype line is the operator's cue and the whole point of D56 decision 3: the
    engine never synthesizes a style at runtime (that would break FR-295's registry authority), so
    a miss is WRITTEN DOWN and the operator authors the missing style deliberately. It is styled as
    a note rather than as provenance because it is the one line on this card that asks for an
    action. Silent — both of them — on every rotation-mode run, every override brief and every
    pre-v2.4.0 `meta.yaml`, which all carry the same empty strings and mean the same thing by them.
    """
    out: list[str] = []
    if reason := " ".join(str(meta.get("style_reason") or "").split()):
        out.append(f'<p class="prov">Style match: {html.escape(reason)}</p>')
    if wanted := " ".join(str(meta.get("style_wanted") or "").split()):
        out.append(f'<p class="note">Wanted archetype: {html.escape(wanted)} — no enabled style '
                   "covers this source, so the rotation baseline rendered it; author one to close "
                   "the gap (FR-337).</p>")
    return out


def _badges(folder: Path, meta: _Meta) -> str:
    """Identity badges, then EVERY degradation tag, looped over the enum (FR-73's single source)."""
    labels = [str(meta.get("platform") or "?"), str(meta.get("creative_format") or "?")]
    # FR-76/FR-73's post-pivot identity: which house style rendered this, which brand system it
    # belongs to, and whether the branding rotation signed THIS one (FR-292 brands a deterministic
    # fraction, so "unsigned" is a normal outcome and is stated rather than left to be inferred
    # from an absent badge). `brief_override` is a style key like any other — it says the override
    # brief, not the registry, was the visual authority for this creative (M14).
    if style := _style_label(meta):
        labels.append(style)
    # FR-318: the brand chip appears only on a SIGNED creative. With branding off (or on an
    # unsigned sibling) the brand selector still filtered the style pool, but naming it here
    # would wave a brand name at an operator who just disabled branding — provenance keeps the
    # selector in meta.yaml; the gallery states only "unsigned".
    if str(meta.get("brand") or "").strip() and meta.get("branded"):
        labels.append(f"brand: {meta['brand']}")
        labels.append("signed")
    elif str(meta.get("brand") or "").strip():
        labels.append("unsigned")
    if meta.get("brief_name"):
        labels.append(f"brief: {meta['brief_name']}")
    labels.append(f"status: {meta.get('status', 'pending')}")
    # FR-328: the gate's own verdict, from `meta.yaml.gauntlet` — the receipt, not the enum. It is
    # a WARN badge when it blocked, because that is the one badge on this page that means "do not
    # publish this", and an ordinary badge otherwise ("pass in 2 rounds" is information, not alarm).
    gate = meta.get("gauntlet") if isinstance(meta.get("gauntlet"), dict) else {}
    if result := str(gate.get("result") or ""):
        rounds = len(gate.get("rounds") or ())
        labels.append(f"gauntlet: {result}" + (f" ({rounds} round(s))" if rounds > 1 else "")
                      + (" · degraded" if gate.get("degraded_gate") else ""))
    vision = str(meta.get("vision_check_result") or "")
    if vision and vision != "not_checked" and not result:
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


def _media_html(folder: Path, meta: _Meta, *, exclude: frozenset[str] = frozenset()) -> str:
    """The creative's own media (FR-72's publishable set), minus anything already shown.

    `exclude` is FR-309's hand-off: a panel-mapped deck renders its slides inside the aligned
    pairs, so this block carries only what those did not claim — usually nothing, in which case it
    is silent rather than repeating the deck under itself. Without an exclusion an empty folder
    still SAYS it is empty: a card with no media and no sentence reads as a rendering bug.
    """
    poster = next(iter(sorted(folder.glob("seed_frame.*"))), None)
    files = [item for item in (sorted(folder.glob("slide_*")) + sorted(folder.glob("image.*"))
                               + sorted(folder.glob("reel.*"))) if item.name not in exclude]
    if not files and poster and poster.name not in exclude:
        files = [poster]
    if not files:
        return "" if exclude else '<div class="media empty">no media on disk</div>'
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


def _refs_html(folder: Path) -> str:
    """The BRIEF photos this creative was rendered with, when it had any (FR-71, D26).

    ONE store now, not two. D46/F3 excised the style reference channel: a meta-style is text-only
    DNA, ships no picture to any render job, and the run-level `refs/<style_key>/` folder that
    used to hold those pictures is no longer written at all — scanning for it would be a search
    for something the run cannot produce. What remains is the asset's own `refs/`, holding an
    override or blend brief's own images, which belong to this creative alone and ARE uploaded.
    Silent for every creative without a brief, which post-pivot is most of them.
    """
    directory = folder / REFS_DIR
    if not directory.is_dir():
        return ""
    tiles: list[str] = []
    for item in sorted(directory.iterdir()):
        if not item.is_file():
            continue
        src = _href(folder.name, REFS_DIR, item.name)
        tiles.append(
            f'<video controls preload="metadata" src="{src}"></video>'
            if item.suffix.lower() in _VIDEO_EXTS
            else f'<a href="{src}"><img loading="lazy" src="{src}" alt="brief reference"></a>'
        )
    return f'<div class="refs"><span>brief images</span>{"".join(tiles)}</div>' if tiles else ""


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
.card.blocked {{ border:2px solid #b3261e; }}
.card.blocked h2::after {{ content:" — BLOCKED, not published"; color:#b3261e; font-size:.7em; }}
.blocked {{ white-space:pre-wrap; background:#fff4f3; border-left:3px solid #b3261e;
  padding:.6rem .8rem; font-size:.85em; }}
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
/* FR-309: source-deck provenance header, then one tile per panel — theirs above, ours below. */
.head {{ border-left:3px solid var(--line); padding:2px 0 2px 10px; margin:0 0 10px; }}
.head p {{ margin:3px 0 0; }}
.ocaption {{ font-size:12px; color:var(--mut); margin:6px 0 0; max-height:6.5em; overflow:auto;
  white-space:pre-wrap; }}
.pairs {{ display:flex; flex-wrap:wrap; gap:10px; align-items:flex-start; }}
.pair {{ flex:0 0 168px; border:1px solid var(--line); border-radius:8px; padding:7px;
  background:var(--bg); }}
.pin {{ font-size:11px; color:var(--mut); margin-bottom:5px; }}
.side {{ margin-top:5px; }}
.side img {{ max-width:100%; max-height:190px; border-radius:6px; display:block; }}
.tag {{ font-size:10px; color:var(--mut); text-transform:uppercase; letter-spacing:.06em; }}
.gap {{ font-size:11px; color:var(--mut); border:1px dashed var(--line); border-radius:6px;
  padding:14px 8px; text-align:center; }}
.ptext {{ font-size:12px; color:var(--fg); margin:5px 0 0; }}
.ptext.none {{ color:var(--mut); font-style:italic; }}
.brief {{ font-size:11px; color:var(--mut); margin:4px 0 0; max-height:7em; overflow:auto; }}
.note {{ font-size:12px; color:var(--warn); background:var(--warnbg); border-radius:6px;
  padding:6px 8px; margin:10px 0 0; }}
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
<p class="howto">Rate this batch on <strong>style adherence</strong>,
<strong>topical accuracy</strong> and <strong>panel fidelity</strong>: does each creative look
like its assigned house style, is it about the topic and the post it quotes verbatim, and does
our slide <em>i</em> carry the words and the content of source panel <em>i</em>? Those three
questions are the whole judgement. The slide texts and the visuals come from the original deck
and are reproduced in our house style; nothing here is cloned from a reference image.</p>
</footer>
</body></html>
"""
