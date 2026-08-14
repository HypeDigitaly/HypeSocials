"""`outputs.gallery` — the offline review page, and FR-309's three-part provenance card.

This file did not exist before D46/W4. The page had been asserted only indirectly (a runner test
checks that its PATH is printed), which was survivable while a card was "media + a few facts" and
is not survivable now: FR-309 made the gallery the surface the operator JUDGES panel fidelity on,
and a card that quietly mis-aligns our slide 3 against source panel 2 would make a broken run look
correct. So the properties pinned here are the ones a wrong page would break silently:

1. **The three parts, in FR-309's order** — the source post's own provenance (author, reach, date,
   permalink, original caption), the source panel strip with each panel's words and visual brief,
   and OUR slides laid against them BY INDEX.
2. **A gap is a gap** (§0.14c) — a source slide that never downloaded and a slide of ours that
   never rendered each leave a LABELLED hole in their own pair. Nothing shifts up, because a strip
   that closes its gaps is a page that lies tidily.
3. **The fallback IS today's card** (§0.14d) — an override-brief carousel binds no post, so its
   `panel_map` is empty and it keeps the pre-D46 single-card layout, exactly as every image and
   reel does.
4. **FR-75 offline-forever** — every `src` is run-relative; an absolute path, a drive letter, a
   traversal or a remote URL in `panel_map.source_image` is DROPPED, not rendered. The only remote
   thing on the page is a permalink inside an `<a href>`, which loads nothing.
5. **NFR-22 never costs a run** — a page that cannot be built returns `None` and logs; the assets
   are on disk either way. A malformed `panel_map` row is dropped, not raised.
6. **FR-73's vocabulary is looped, not listed** — an older `meta.yaml` carrying a tag this build's
   enum does not know still renders, and shows the unknown tag rather than hiding it.

Everything is built on `tmp_path`: real folders, real `meta.yaml` files written as `packager`
writes them, real media bytes. No network, no run, no money — `write_gallery` reads disk and
returns a string, so the page itself is the assertion surface.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from hypesocials.models import DegradationTag
from hypesocials.outputs import gallery, packager

JPEG = b"\xff\xd8fake-jpeg-bytes"
MP4 = b"\x00\x00\x00\x18ftypmp42"
#: The longest permalink in the captured Virlo corpus — a real post URL shape, so the "the only
#: remote string on the page is a permalink" assertion is measured against something realistic.
PERMALINK = "https://www.tiktok.com/@ai_prompt_and_technology/photo/758029432720154959"


# --------------------------------------------------------------------------- builders


def meta(**overrides: Any) -> dict[str, Any]:
    """One `meta.yaml` document, in the shape `generate._record` writes it (FR-73)."""
    base: dict[str, Any] = {
        "asset_id": "0001_carousel_linkedin", "source": "m1::ai-tool-stacks",
        "source_name": "AI tool stacks", "platform": "linkedin", "creative_format": "carousel",
        "status": "success", "style_key": "flat-card", "brand": "hypelead", "branded": False,
        "topic_key": "ai-tool-stacks", "aspect_ratio_requested": "1:1",
        "estimated_cost_usd": 0.12, "actual_cost_usd": 0.13, "degradations": [],
        "copy_source_post_id": "", "copy_source_refs": {}, "model_ids": [],
        "source_post": None, "source_panel_count": 0, "panel_map": [],
    }
    base.update(overrides)
    return base


def source_post(**overrides: Any) -> dict[str, Any]:
    """FR-73's nested `source_post` — whose deck this creative is a rendering OF."""
    base: dict[str, Any] = {
        "post_id": "7412998877", "url": PERMALINK, "author": "creator", "views": 1_240_000,
        "published_at": "2026-08-01T09:30:00+00:00",
        "caption": "the five tools I actually use  #ai #tools",
    }
    base.update(overrides)
    return base


def row(slide: int, position: int, *, text: str = "", label: str = "", brief: str = "",
        image: str | None = "") -> dict[str, Any]:
    """One `panel_map` row, both halves of the join present (`generate._panel_map`'s one schema).

    `image=""` defaults to the conventional relative path for that position, `None` is the slide
    whose download failed (§0.14c case b), and any other string is passed through so the FR-75
    rejection cases can be written literally.
    """
    if image == "":
        image = f"source/7412998877/slide_{position:02d}.jpg"
    return {"slide": slide, "source_position": position, "source_text": text,
            "ref_label": label or f"P1.panel.{position}", "visual_brief": brief,
            "source_image": image}


def asset(run: Path, document: dict[str, Any], *, media: tuple[str, ...] = (),
          refs: tuple[str, ...] = (), skip_reason: str = "", caption: str = "") -> Path:
    """One asset folder on disk: media bytes, an optional brief-reference store, and `meta.yaml`."""
    folder = run / str(document["asset_id"])
    folder.mkdir(parents=True, exist_ok=True)
    for name in media:
        (folder / name).write_bytes(MP4 if name.endswith(".mp4") else JPEG)
    for name in refs:
        (folder / packager.REFS_DIR).mkdir(exist_ok=True)
        (folder / packager.REFS_DIR / name).write_bytes(JPEG)
    if skip_reason:
        (folder / packager.SKIP_REASON_FILE).write_text(skip_reason, encoding="utf-8")
    if caption:
        (folder / "caption.txt").write_text(caption, encoding="utf-8")
    (folder / packager.META_FILE).write_text(yaml.safe_dump(document), encoding="utf-8")
    return folder


def store_source(run: Path, post_id: str = "7412998877", *, slides: int = 3) -> Path:
    """The run-level source-slide store `sources/slide_intel` writes (§0.13, FR-71 amended)."""
    folder = run / packager.SOURCE_DIR / post_id
    folder.mkdir(parents=True, exist_ok=True)
    for position in range(1, slides + 1):
        (folder / f"slide_{position:02d}.jpg").write_bytes(JPEG)
    (folder / packager.SOURCE_META_FILE).write_text(
        yaml.safe_dump({"post_id": post_id, "panel_count": slides}), encoding="utf-8")
    return folder


def page(run: Path) -> str:
    """Build the page and hand back its text — the one call every test below makes."""
    written = gallery.write_gallery(run, title="HypeSocials Run")
    assert written is not None and written.name == gallery.GALLERY_FILE
    return written.read_text(encoding="utf-8")


def media_srcs(html_text: str) -> list[str]:
    """Every URL the BROWSER would fetch — `src` and `poster`, never `href` (FR-75)."""
    return re.findall(r'(?:src|poster)="([^"]*)"', html_text)


class Log:
    """The `.warn(event_type, message, **data)` slice `write_gallery` uses (NFR-22)."""

    def __init__(self) -> None:
        self.warnings: list[tuple[str, str]] = []

    def warn(self, event_type: str, message: str = "", **data: Any) -> str:
        self.warnings.append((event_type, message))
        return event_type

    def keys(self) -> list[str]:
        return [event_type for event_type, _ in self.warnings]


def deck(run: Path, **overrides: Any) -> Path:
    """The standard three-panel mapped deck: source store, three rows, three delivered slides."""
    store_source(run)
    document = meta(
        source_post=source_post(), source_panel_count=3, slide_count=3,
        copy_source_post_id="7412998877",
        copy_source_refs={"slide_1": "P1.panel.1", "caption": "P1.caption"},
        panel_map=[row(1, 1, text="Panel one", brief="hero image, heading centred"),
                   row(2, 2, text="Panel two", brief="two-column table, four rows"),
                   row(3, 3, text="Panel three", brief="line chart, three series")])
    document.update(overrides)
    return asset(run, document, media=("slide_01.jpg", "slide_02.jpg", "slide_03.jpg"))


# --------------------------------------------------------------- FR-309: the three-part card


def test_fr309_a_panel_mapped_deck_shows_provenance_then_their_slides_then_ours(
    tmp_path: Path,
) -> None:
    """FR-309 part by part, in its stated order — the whole point of the amended gallery.

    The header answers "whose deck is this" with the five facts the operator would otherwise have
    to open Virlo for (author, reach, date, post id, permalink) plus the creator's OWN caption; the
    strip shows each SOURCE panel with the words extracted from it and the visual brief that drove
    our render; and our slide for that index sits in the SAME tile, so judging panel fidelity is a
    glance rather than a memory exercise.
    """
    deck(tmp_path)

    html_text = page(tmp_path)

    head = html_text.split('<div class="pairs">')[0]
    assert "@creator" in head, "the author is @-prefixed even when Virlo stored it bare"
    assert "1,240,000 views" in head and "2026-08-01T09:30:00+00:00" in head
    assert "post 7412998877" in head
    assert f'<a href="{PERMALINK}">the original post</a>' in head
    assert "the five tools I actually use" in head
    # part 2 — their slides, from the run-level store, by relative path
    assert './source/7412998877/slide_01.jpg' in html_text
    assert "“Panel two”" in html_text and "two-column table, four rows" in html_text
    assert "P1.panel.3" in html_text, "the ref label the words were quoted under is on the tile"
    # part 3 — ours, in the same tile, index stated on the tile itself
    for index in (1, 2, 3):
        assert f"slide {index} ← source panel {index}" in html_text
        assert f"./0001_carousel_linkedin/slide_{index:02d}.jpg" in html_text
    assert html_text.count('<div class="pair">') == 3
    # the deck's slides are shown INSIDE the pairs, so the plain media block has nothing left
    assert '<div class="media">' not in html_text


def test_fr309_an_undownloaded_source_panel_is_a_stated_gap_and_never_a_shift(
    tmp_path: Path,
) -> None:
    """§0.14c case (b) at the page: a 404 costs that panel its picture and nothing else.

    The pairing is what makes this safe. Two independent strips would line up only while both were
    full — the first missing source image would slide every later tile by one and put our slide 3
    against their panel 2, which is precisely the mis-reading FR-304 exists to prevent.
    """
    store_source(tmp_path)
    asset(tmp_path, meta(
        source_post=source_post(), source_panel_count=3, slide_count=3,
        panel_map=[row(1, 1, text="Panel one"), row(2, 2, text="Panel two", image=None),
                   row(3, 3, text="Panel three")]),
        media=("slide_01.jpg", "slide_02.jpg", "slide_03.jpg"))

    html_text = page(tmp_path)

    assert html_text.count('<div class="gap">source slide not downloaded</div>') == 1
    # the words survived the lost picture — the text came from Virlo, not from the image
    assert "“Panel two”" in html_text
    second = html_text.split('<div class="pair">')[2]
    assert "slide 2 ← source panel 2" in second
    assert "source slide not downloaded" in second
    assert "./0001_carousel_linkedin/slide_02.jpg" in second, "OUR slide 2 is still in ITS tile"
    assert "./source/7412998877/slide_03.jpg" in html_text.split('<div class="pair">')[3]


def test_fr309_a_slide_we_never_delivered_leaves_its_own_hole(tmp_path: Path) -> None:
    """The mirror case (FR-20/95): a partial deck states which of OUR slides is missing.

    `_our_slides` parses the number out of the filename rather than counting a sorted list, so a
    deck that lost slide 2 puts `slide_03.jpg` against source panel 3 — the alignment survives the
    loss instead of being quietly re-based by it.
    """
    store_source(tmp_path)
    asset(tmp_path, meta(
        source_post=source_post(), source_panel_count=3, slide_count=3,
        degradations=[DegradationTag.INCOMPLETE.value],
        panel_map=[row(1, 1, text="Panel one"), row(2, 2, text="Panel two"),
                   row(3, 3, text="Panel three")]),
        media=("slide_01.jpg", "slide_03.jpg"), skip_reason="slide 2: provider_fail")

    html_text = page(tmp_path)

    assert html_text.count('<div class="gap">slide not delivered</div>') == 1
    third = html_text.split('<div class="pair">')[3]
    assert "slide 3 ← source panel 3" in third
    assert "./0001_carousel_linkedin/slide_03.jpg" in third, "slide 3 did not slide up into slot 2"
    assert "Skipped: slide 2: provider_fail" in html_text
    assert '<span class="badge warn">incomplete</span>' in html_text


def test_fr309_a_wordless_source_panel_says_so_rather_than_showing_an_empty_quote(
    tmp_path: Path,
) -> None:
    """§0.14a's empty slot, rendered honestly. `“”` would read as a transcription failure; "no
    words on this panel" is the fact — Virlo transcribed nothing and vision filled nothing, and
    our slide for that index renders wordless on purpose (FR-304)."""
    store_source(tmp_path)
    asset(tmp_path, meta(
        source_post=source_post(), source_panel_count=2, slide_count=2,
        panel_map=[row(1, 1, text="Panel one"), row(2, 2, text="", label="")]),
        media=("slide_01.jpg", "slide_02.jpg"))

    html_text = page(tmp_path)

    assert '<p class="ptext none">no words on this panel</p>' in html_text
    assert "“”" not in html_text


def test_fr304_a_truncated_deck_states_the_cut_instead_of_making_the_operator_count(
    tmp_path: Path,
) -> None:
    """§0.4′'s ceiling cut, and the distinction the note refuses to blur.

    A three-slide card under a nine-panel source looks identical whether the tail was never ORDERED
    (`panels_truncated`) or was ordered and lost. They are different facts about the same-looking
    page, so the note names the tag when it is there and stays neutral when it is not.
    """
    truncated = deck(tmp_path, source_panel_count=9,
                     degradations=[DegradationTag.PANELS_TRUNCATED.value])

    html_text = page(tmp_path)
    assert ("Showing the first 3 of 9 source panels — the tail was never ordered "
            "(panels_truncated), not lost in rendering.") in html_text
    assert '<span class="badge warn">panels truncated</span>' in html_text

    (truncated / packager.META_FILE).write_text(
        yaml.safe_dump(meta(source_post=source_post(), source_panel_count=9, slide_count=3,
                            panel_map=[row(n, n, text=f"Panel {n}") for n in (1, 2, 3)])),
        encoding="utf-8")
    neutral = page(tmp_path)
    # `html.escape` owns the apostrophe, which is the point of asserting on the RENDERED page
    # rather than on the sentence the module builds.
    assert "Our 3 slide(s) against the source deck&#x27;s 9 panels." in neutral
    assert "never ordered" not in neutral


def test_fr309_a_deck_whose_row_count_matches_the_source_gets_no_note_at_all(
    tmp_path: Path,
) -> None:
    """Nothing was cut, so there is nothing to say — a note on every card is a note nobody reads."""
    deck(tmp_path)

    assert '<p class="note">' not in page(tmp_path)


def test_fr309_a_source_post_that_could_not_be_resolved_prints_its_id_alone(
    tmp_path: Path,
) -> None:
    """`generate._record` writes `{post_id}` alone when the topic roster can no longer resolve the
    bound post, and the page renders exactly that: the id is a fact, and a blank author beside a
    `0 views` would be invented provenance wearing the same typeface as the real thing."""
    store_source(tmp_path)
    asset(tmp_path, meta(source_post={"post_id": "7412998877"}, source_panel_count=2,
                         slide_count=2,
                         panel_map=[row(1, 1, text="Panel one"), row(2, 2, text="Panel two")]),
          media=("slide_01.jpg", "slide_02.jpg"))

    html_text = page(tmp_path)

    assert "Source deck: post 7412998877" in html_text
    assert "views" not in html_text.split('<div class="pairs">')[0]
    assert "the original post" not in html_text, "no url was resolved, so no link is offered"


# ------------------------------------------------------------- §0.14d: the fallback IS the card


def test_0_14d_an_override_brief_carousel_keeps_the_single_card_layout(tmp_path: Path) -> None:
    """An override brief binds no source post (§0.14d), so FR-304 never applied to it and there is
    nothing to align against. The empty `panel_map` IS the routing signal, and the card it routes
    to is the pre-D46 one — media, facts, topic, receipt — unchanged."""
    asset(tmp_path, meta(asset_id="0001_carousel_linkedin", style_key="brief_override",
                         brief_name="ai-audit-cta", source_name="", topic_key="",
                         slide_count=2, panel_map=[], source_post=None),
          media=("slide_01.jpg", "slide_02.jpg"), caption="Book the audit.")

    html_text = page(tmp_path)

    card = html_text.split("<article")[1].split("</article>")[0]
    assert '<div class="pairs">' not in card and "source panel" not in card
    assert "Source deck:" not in card
    assert '<div class="media">' in html_text
    assert "./0001_carousel_linkedin/slide_01.jpg" in html_text
    assert "./0001_carousel_linkedin/slide_02.jpg" in html_text
    assert "brief: ai-audit-cta" in html_text and "style: brief_override" in html_text
    assert "Book the audit." in html_text


def test_an_image_and_a_reel_are_untouched_by_fr309(tmp_path: Path) -> None:
    """The other two formats never had panels. The reel still draws its own first frame through the
    seed frame as `poster` (D10 — no ffmpeg in this project), and neither card grows a strip."""
    asset(tmp_path, meta(asset_id="0001_image_linkedin", creative_format="image", slide_count=0),
          media=("image.jpg",))
    asset(tmp_path, meta(asset_id="0002_reel_tiktok", creative_format="reel", platform="tiktok",
                         slide_count=0), media=("reel.mp4", "seed_frame.jpg"))

    html_text = page(tmp_path)

    assert '<div class="pairs">' not in html_text
    assert './0001_image_linkedin/image.jpg' in html_text
    assert ('<video controls preload="metadata" poster="./0002_reel_tiktok/seed_frame.jpg" '
            'src="./0002_reel_tiktok/reel.mp4"></video>') in html_text
    assert "delivered 2 of 2" in html_text


def test_a_slide_no_panel_row_claimed_is_still_shown_below_the_pairs(tmp_path: Path) -> None:
    """Media on disk is never hidden by a mapping that did not mention it — a stray slide (an older
    meta, a deck re-rendered longer than its map) shows under the strip rather than vanishing."""
    store_source(tmp_path)
    asset(tmp_path, meta(source_post=source_post(), source_panel_count=2, slide_count=3,
                         panel_map=[row(1, 1, text="Panel one"), row(2, 2, text="Panel two")]),
          media=("slide_01.jpg", "slide_02.jpg", "slide_03.jpg"))

    html_text = page(tmp_path)

    trailing = html_text.split('<div class="media">')[1]
    assert "./0001_carousel_linkedin/slide_03.jpg" in trailing
    assert "slide_01" not in trailing and "slide_02" not in trailing, \
        "the pairs already showed those two; the deck is not repeated under itself"
    assert media_srcs(html_text).count("./0001_carousel_linkedin/slide_01.jpg") == 1


# --------------------------------------------------------------------------- FR-75: offline


@pytest.mark.parametrize("hostile", [
    "https://cdn.virlo.test/7412998877/1.jpg",       # a hotlink — the page stops being offline
    "http://cdn.virlo.test/1.jpg",
    "C:/output/20260813_101010/source/p1/slide_01.jpg",  # an absolute Windows path
    "/var/run/source/p1/slide_01.jpg",               # an absolute POSIX path
    "../../../etc/passwd",                           # a traversal
    "source/../../secret/slide_01.jpg",
    "..\\..\\secret\\slide_01.jpg",                  # the same, backslashed
])
def test_fr75_a_source_image_that_is_not_run_relative_is_dropped_not_rendered(
    hostile: str, tmp_path: Path,
) -> None:
    """FR-75 as amended: `source/` is an allowed relative root, and the hotlink ban stays.

    One remote byte and the page stops being the artifact FR-75 promises — openable offline, from
    a USB stick, forever — and a Virlo CDN URL would additionally be dead within days. Rejection
    degrades the tile to exactly the gap a failed download already leaves, which is a shape the
    operator already knows how to read.
    """
    store_source(tmp_path)
    asset(tmp_path, meta(source_post=source_post(), source_panel_count=1, slide_count=1,
                         panel_map=[row(1, 1, text="Panel one", image=hostile)]),
          media=("slide_01.jpg",))

    html_text = page(tmp_path)

    assert hostile not in html_text and hostile.replace("\\", "/") not in html_text
    assert "source slide not downloaded" in html_text
    assert all(src.startswith("./") for src in media_srcs(html_text))


def test_fr75_the_only_remote_string_on_the_page_is_a_permalink_nobody_has_to_load(
    tmp_path: Path,
) -> None:
    """Self-contained (FR-75/NFR-22): no CDN, no external font, no script, no fetch of any kind.

    The permalinks are the deliberate exception and they are `<a href>`s — a link is a place the
    operator may choose to go, not a byte the page needs in order to render.
    """
    deck(tmp_path, virlo_url="https://virlo.app/trends/ai-tool-stacks")

    html_text = page(tmp_path)

    assert all(src.startswith("./") for src in media_srcs(html_text)), media_srcs(html_text)
    for match in re.finditer(r'https?://\S+', html_text):
        prefix = html_text[:match.start()]
        assert prefix.endswith('<a href="'), f"a remote URL outside an anchor: {match.group()}"
    assert "<script" not in html_text and "@import" not in html_text
    assert "<link" not in html_text, "no external stylesheet, no favicon fetch"
    # FR-150 as amended: three judging criteria, panel fidelity among them.
    assert "panel fidelity" in html_text and "topical accuracy" in html_text


def test_the_run_level_source_and_refs_stores_are_never_mistaken_for_creatives(
    tmp_path: Path,
) -> None:
    """`source/` and `refs/` sit beside the asset folders and are NOT assets (FR-71/72).

    The skip is by name and deliberate rather than incidental: both stores are given a `meta.yaml`
    here precisely so that "it has no meta.yaml anyway" cannot be what passes this test. A future
    store that DID hold one must still not become a card — and neither may ever be published.
    """
    store_source(tmp_path)
    (tmp_path / packager.SOURCE_DIR / packager.META_FILE).write_text(
        yaml.safe_dump(meta(asset_id="source")), encoding="utf-8")
    (tmp_path / packager.REFS_DIR).mkdir(parents=True, exist_ok=True)
    (tmp_path / packager.REFS_DIR / packager.META_FILE).write_text(
        yaml.safe_dump(meta(asset_id="refs")), encoding="utf-8")
    asset(tmp_path, meta(creative_format="image", slide_count=0), media=("image.jpg",))

    html_text = page(tmp_path)

    assert html_text.count("<article") == 1, "one creative on disk, one card"
    assert "delivered 1 of 1" in html_text
    assert ">source</h2>" not in html_text and ">refs</h2>" not in html_text


def test_an_assets_own_brief_photos_still_show_and_the_style_store_is_gone(
    tmp_path: Path,
) -> None:
    """FR-71/D26 post-F3: ONE reference store left. A brief's own photos belong to this creative
    and were really uploaded, so they are shown; the run-level style-reference store the pre-D46
    page also scanned is not written at all any more, because a meta-style ships no pixels."""
    asset(tmp_path, meta(creative_format="image", slide_count=0, brief_name="product-shot"),
          media=("image.jpg",), refs=("product-shot-01.png",))

    html_text = page(tmp_path)

    assert "brief images" in html_text
    assert "./0001_carousel_linkedin/refs/product-shot-01.png" in html_text


# ------------------------------------------------------------- FR-73 / FR-298: badges & receipt


def test_fr73_an_unknown_degradation_tag_from_an_older_meta_is_shown_not_hidden(
    tmp_path: Path,
) -> None:
    """The badge list is a LOOP over `models.DegradationTag`, so a new tag needs no change here —
    and a tag this build does not know (a meta.yaml written by a newer or older run) is printed
    after the known ones instead of being silently dropped. A page that hides a degradation it
    cannot name is worse than one that shows a word the reader has to look up."""
    deck(tmp_path, degradations=["vision_transcribed", "a_tag_from_the_future",
                                 DegradationTag.PANELS_TRUNCATED.value])

    html_text = page(tmp_path)

    badges = re.findall(r'<span class="badge warn">([^<]+)</span>', html_text)
    assert badges == ["vision transcribed", "panels truncated", "a tag from the future"], \
        "known tags in enum order, then the unknown one — nothing dropped"


def test_fr321_the_page_header_names_a_deck_that_shipped_short(tmp_path: Path) -> None:
    """FR-321: a partial deck is counted INSIDE `delivered` — it did ship — and then named.

    This is the opening line of the page the operator reviews the run on, so "delivered 2 of 2"
    over a deck missing a slide is the same silence the spend table's `7/8` removed. The
    predicate is the pair `carousel.package()` writes, read the same way the money module reads
    it, because two implementations of "is this deck short" are free to disagree.
    """
    deck(tmp_path, asset_id="0001_carousel_linkedin", slide_count=2, slides_ordered=3)
    asset(tmp_path, meta(asset_id="0002_image_linkedin", creative_format="image",
                         actual_cost_usd=0.04), media=("image.jpg",))

    html_text = page(tmp_path)

    assert "delivered 2 of 2 (1 partial)" in html_text


def test_fr321_a_whole_deck_and_a_pre_requirement_meta_leave_the_header_unqualified(
    tmp_path: Path,
) -> None:
    """The silence has to be the default, twice over.

    A deck that delivered everything it ordered is not partial, and a `meta.yaml` written before
    FR-321 existed carries no `slides_ordered` and therefore makes no claim either way — guessing
    one from `missing_slide_numbers` here would be a second implementation of the predicate,
    disagreeing with the spend table's on exactly the runs nobody re-checks.
    """
    deck(tmp_path, asset_id="0001_carousel_linkedin", slide_count=3, slides_ordered=3)
    deck(tmp_path, asset_id="0002_carousel_linkedin", slide_count=2)  # no `slides_ordered` key

    html_text = page(tmp_path)

    assert "delivered 2 of 2 · " in html_text
    assert "partial" not in html_text


def test_fr318_the_brand_chip_appears_on_a_signed_creative_and_nowhere_else(
    tmp_path: Path,
) -> None:
    """FR-318: `brand:` is a claim about the CREATIVE, so it may only appear where the wordmark did.

    `meta.brand` records which brand's rotation and style pool this run drew on — it is written on
    every creative, signed or not, and it stays in meta.yaml as provenance. The gallery is a review
    surface, not provenance: waving "brand: hypelead" at an operator who just switched branding
    off (now the default) says the batch is self-branded when nothing on it is. An unsigned card
    therefore states only `unsigned`.
    """
    deck(tmp_path, asset_id="0001_carousel_linkedin", brand="hypelead", branded=False)

    html_text = page(tmp_path)

    chips = re.findall(r'<span class="badge">([^<]+)</span>', html_text)
    assert "unsigned" in chips
    assert "signed" not in chips
    assert not any(chip.startswith("brand:") for chip in chips), \
        "no brand name on a creative that carries no wordmark"
    assert "brand: hypelead" not in html_text


def test_fr318_a_signed_creative_still_names_the_brand_it_was_signed_with(
    tmp_path: Path,
) -> None:
    """The complement: a creative that DID carry the wordmark names the brand beside `signed`.

    Both chips, in that order, because "signed" alone leaves the operator of a two-brand config
    with no way to tell which wordmark is on the picture in front of them.
    """
    deck(tmp_path, brand="hypelead", branded=True)

    html_text = page(tmp_path)

    chips = re.findall(r'<span class="badge">([^<]+)</span>', html_text)
    assert "brand: hypelead" in chips and "signed" in chips
    assert chips.index("brand: hypelead") + 1 == chips.index("signed")
    assert "unsigned" not in chips


def test_fr298_the_receipt_names_the_post_and_reads_the_slots_in_reading_order(
    tmp_path: Path,
) -> None:
    """FR-298: the card says WHICH exact strings were quoted, under the same `P<n>.<kind>[.<i>]`
    grammar the copy call was offered — so a label on the card traces straight to the post roster
    in `run.log`. The lead slot is the most visible one that was quoted, not the first key in a
    dict, because the operator reads the biggest pixels first."""
    deck(tmp_path, copy_source_refs={"caption": "P1.caption", "slide_1": "P1.panel.1",
                                     "headline": "P1.panel.1"})

    html_text = page(tmp_path)

    assert "Quotes P1.panel.1 verbatim as the headline · post 7412998877" in html_text
    assert "Also quoted: slide 1 P1.panel.1 · caption P1.caption" in html_text


def test_a_creative_that_quoted_nothing_shows_an_empty_receipt_rather_than_a_blank_one(
    tmp_path: Path,
) -> None:
    """A burnt-post refusal (FR-307) and an override brief both ship OUR words, so there is no
    verbatim receipt to print. Silence is the honest rendering — the `no_fresh_post_available`
    badge is already saying why, and a receipt line with nothing after it reads as a bug."""
    asset(tmp_path, meta(creative_format="image", slide_count=0, copy_source_refs={},
                         degradations=[DegradationTag.NO_FRESH_POST_AVAILABLE.value,
                                       DegradationTag.NO_ONIMAGE_TEXT.value]),
          media=("image.jpg",))

    html_text = page(tmp_path)

    assert "Quotes" not in html_text and "Also quoted" not in html_text
    assert '<span class="badge warn">no onimage text</span>' in html_text
    assert '<span class="badge warn">no fresh post available</span>' in html_text


# --------------------------------------------------------------------------- NFR-22: robustness


def test_nfr22_a_malformed_panel_map_row_is_dropped_rather_than_losing_the_page(
    tmp_path: Path,
) -> None:
    """One bad row must not cost the whole gallery: NFR-22 pays for a template error with every
    card on the page, and a hand-edited or half-written `meta.yaml` is a cheap way to get one."""
    store_source(tmp_path)
    asset(tmp_path, meta(source_post=source_post(), source_panel_count=2, slide_count=2,
                         panel_map=["not a row", None, row(2, 2, text="Panel two")]),
          media=("slide_01.jpg", "slide_02.jpg"))

    html_text = page(tmp_path)

    assert html_text.count('<div class="pair">') == 1
    assert "slide 2 ← source panel 2" in html_text
    assert "not a row" not in html_text


def test_nfr22_a_page_that_cannot_be_built_returns_none_and_says_where_the_assets_are(
    tmp_path: Path,
) -> None:
    """"Never blocks delivery": the assets are on disk whatever happens to the HTML, so a failure
    is a warning and a `None`, never an exception climbing back into the run."""
    log = Log()

    assert gallery.write_gallery(tmp_path / "no-such-run", log=log) is None
    assert log.keys() == ["gallery_write_failed"]
    assert "no-such-run" in log.warnings[0][1]


def test_the_page_is_rebuilt_from_disk_on_every_call(tmp_path: Path) -> None:
    """FR-76: the caller just calls it again whenever assets land — there is no state to thread and
    no incremental bookkeeping to get wrong, because the run folder IS the state."""
    asset(tmp_path, meta(asset_id="0001_image_linkedin", creative_format="image", slide_count=0),
          media=("image.jpg",))

    first = page(tmp_path)
    assert first.count("<article") == 1 and "delivered 1 of 1 · $0.13 spent" in first

    deck(tmp_path)
    second = page(tmp_path)

    assert second.count("<article") == 2 and "delivered 2 of 2 · $0.26 spent" in second
    assert page(tmp_path) == second, "same disk, same page"


def test_an_empty_run_folder_says_so_instead_of_rendering_a_bare_shell(tmp_path: Path) -> None:
    """The page exists from the first call, before any creative lands — a blank card grid would
    read as a rendering failure at exactly the moment the operator is watching for one."""
    html_text = page(tmp_path)

    assert "No asset folders yet" in html_text
    assert "delivered 0 of 0" in html_text


def test_the_card_is_drawn_from_the_meta_that_generate_actually_writes(tmp_path: Path) -> None:
    """The loop the fabricated documents above cannot close: FIELD NAMES, end to end.

    Every other test here hand-writes a `meta.yaml`, which pins the page against a document a human
    typed — so a rename anywhere along `CopyProvenance` -> `generate._record` -> `AssetRecord` ->
    `packager`'s serializer would leave both halves internally consistent and the real page blank.
    This one runs the actual writer over the actual dataclasses and reads the actual file back, so
    the three-part card is asserted against bytes the pipeline produced.
    """
    from datetime import datetime, timezone

    from hypesocials import generate
    from hypesocials.config import Config
    from hypesocials.copywrite import CopyProvenance
    from hypesocials.models import PlanEntry, SourcePost, TrendItem

    class Intel:
        """`sources.slide_intel.SlideIntel`, duck-typed — `generate` imports nothing from
        `sources`, so the join between them is an attribute contract, not a type."""

        degradations = ["vision_transcribed"]

        def slide(self, position: int) -> Any:
            return type("S", (), {"visual_brief": f"brief for panel {position}"})()

        def relative_image(self, position: int) -> str:
            return f"source/7412998877/slide_{position:02d}.jpg"

    store_source(tmp_path, slides=2)
    entry = PlanEntry(order=0, asset_id="0001_carousel_linkedin", creative_format="carousel",
                      platform="linkedin", language="en", aspect_ratio="1:1",
                      trend_key="t1", style_key="flat-card", slide_count=2,
                      source_post_id="7412998877")
    env = generate.Env(
        config=Config(), run_dir=tmp_path, engine=None, budget=None, log=None, ledger=None,
        trends={"t1": TrendItem(
            history_key="t1", monitor_id="m1", name="AI tool stacks", topic_key="ai-tool-stacks",
            posts=[SourcePost(post_id="7412998877", url=PERMALINK, author="creator",
                              views=1_240_000, is_slideshow=True, panel_count=2,
                              caption="the five tools I actually use",
                              published_at=datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc))])},
        copy_provenance={entry.asset_id: CopyProvenance(
            post_id="7412998877", refs={"slide_1": "P1.panel.1"}, source_panel_count=2,
            panel_map=[{"slide": 1, "source_position": 1, "source_text": "Panel one",
                        "ref_label": "P1.panel.1"},
                       {"slide": 2, "source_position": 2, "source_text": "Panel two",
                        "ref_label": "P1.panel.2"}])},
        slide_intel={"7412998877": Intel()})
    folder = packager.AssetFolder(tmp_path, generate._record(entry, env))
    (folder.path / "slide_01.jpg").write_bytes(JPEG)
    (folder.path / "slide_02.jpg").write_bytes(JPEG)
    folder.finish()

    html_text = page(tmp_path)

    assert "Source deck: @creator · 1,240,000 views · 2026-08-01T09:30:00+00:00" in html_text
    assert "the five tools I actually use" in html_text
    assert "slide 1 ← source panel 1" in html_text and "slide 2 ← source panel 2" in html_text
    assert "“Panel two”" in html_text and "brief for panel 2" in html_text
    assert "./source/7412998877/slide_02.jpg" in html_text
    assert "./0001_carousel_linkedin/slide_02.jpg" in html_text
    assert '<span class="badge warn">vision transcribed</span>' in html_text
    assert "Quotes P1.panel.1 verbatim as the slide 1 · post 7412998877" in html_text


def test_a_failed_creative_still_gets_a_card_saying_what_it_would_have_been(
    tmp_path: Path,
) -> None:
    """A failure is not an absence: the card is drawn dashed, states its status, and keeps the
    provenance and the caption the run already paid for (FR-74)."""
    store_source(tmp_path)
    asset(tmp_path, meta(status="failed", source_post=source_post(), source_panel_count=2,
                         slide_count=2, actual_cost_usd=0.0,
                         degradations=[DegradationTag.ABANDONED.value],
                         panel_map=[row(1, 1, text="Panel one"), row(2, 2, text="Panel two")]),
          skip_reason="abandoned at the deadline", caption="the caption survives")

    html_text = page(tmp_path)

    assert '<article class="card failed">' in html_text
    assert "status: failed" in html_text and "delivered 0 of 1" in html_text
    assert html_text.count('<div class="gap">slide not delivered</div>') == 2
    assert "the caption survives" in html_text
    assert "Skipped: abandoned at the deadline" in html_text
