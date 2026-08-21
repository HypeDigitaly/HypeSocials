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
7. **The style badge says WHICH ALGORITHM chose the look** (FR-337, v2.4.0/D56) — `matched/high`
   or `rotation`, with `rotation_fallback` deliberately collapsed onto `rotation` and the
   distinction carried by the `style match degraded` tag beside it. The matcher's reason and its
   wanted-archetype note are MODEL-AUTHORED strings landing in HTML, so both are whitespace-
   collapsed and `html.escape`d like every other string this module reads off disk; and a
   `meta.yaml` written before v2.4.0 keeps the bare label it always had.

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


# ------------------------------------------------- D54/FR-331: a COMPRESSED deck on the same card
#
# A compressed deck reaches this page with two things every deck before it lacked: `copy_mode:
# compress` at the top of `meta.yaml`, and `compressed: true` on every `panel_map` row (FR-73 as
# amended). It also reaches it with two things every OTHER deck has and it does not — a `ref_label`
# on each row, and any entry in `copy_source_refs` — because a compressed slide quotes no label
# (FR-302 as amended).
#
# That last pair is what makes these tests worth having. FR-309's alignment, its gap handling and
# its routing signal must not depend on a label being there, or the mode that ships no labels would
# ship no provenance card either — and the provenance card is the only surface on which an operator
# can judge whether a compression kept the panel's meaning.


def compressed_row(slide: int, position: int, *, text: str = "", original: str = "",
                   brief: str = "", image: str | None = "") -> dict[str, Any]:
    """One `panel_map` row as `copywrite._compressed_deck` writes it (D54/FR-331).

    Three differences from `row()` above and each is contractual: `ref_label` is EMPTY (nothing was
    quoted), `compressed` is True, and `source_text_original` carries the panel the model started
    from — which is the length FR-309's amendment measures "compressed from N chars" off.
    """
    built = row(slide, position, text=text, label="", brief=brief, image=image)
    built["ref_label"] = ""
    built["compressed"] = True
    built["source_text_original"] = original or text
    return built


def compressed_deck(run: Path, **overrides: Any) -> Path:
    """The standard three-panel deck, written as a COMPRESS-mode run writes it."""
    store_source(run)
    document = meta(
        source_post=source_post(), source_panel_count=3, slide_count=3,
        copy_source_post_id="7412998877",
        copy_source_refs={},  # FR-302 as amended: a compressed slide resolved no labels
        copy_mode="compress",
        panel_map=[
            compressed_row(1, 1, text="Ship it, then measure.",
                           original="Panel one. " + "It keeps explaining at length. " * 8,
                           brief="hero image, heading centred"),
            compressed_row(2, 2, text="Measure it, then cut.",
                           original="Panel two. " + "It also explains at length. " * 8,
                           brief="two-column table, four rows"),
            compressed_row(3, 3, text="Cut it, then ship again.",
                           original="Panel three. " + "And it explains once more. " * 8,
                           brief="line chart, three series")])
    document.update(overrides)
    return asset(run, document, media=("slide_01.jpg", "slide_02.jpg", "slide_03.jpg"))


def test_fr309_a_compressed_deck_still_gets_the_three_part_card_and_aligns_by_index(
    tmp_path: Path,
) -> None:
    """The routing signal is the non-empty `panel_map`, not the presence of a ref label.

    This matters because a compressed deck is the one shape whose rows carry no labels at all. If
    the card had keyed anything off `ref_label`, D54 would have silently demoted every deck in the
    mode to the single-card fallback — losing exactly the side-by-side view the operator needs to
    judge whether a compression kept its panel's meaning (FR-150's fidelity check).
    """
    compressed_deck(tmp_path)

    html_text = page(tmp_path)

    head = html_text.split('<div class="pairs">')[0]
    assert "@creator" in head and "post 7412998877" in head, "part 1: the provenance header"
    assert f'<a href="{PERMALINK}">the original post</a>' in head
    assert html_text.count('<div class="pair">') == 3, "one tile per OUR slide, none dropped"
    for index in (1, 2, 3):
        assert f"slide {index} ← source panel {index}" in html_text
        assert f"./source/7412998877/slide_{index:02d}.jpg" in html_text
        assert f"./0001_carousel_linkedin/slide_{index:02d}.jpg" in html_text
    assert "“Measure it, then cut.”" in html_text, "the SHIPPED string sits on its own tile"
    assert "two-column table, four rows" in html_text, "the FR-308 brief survives the mode"


def test_fr73_the_compressed_receipt_survives_a_round_trip_through_meta_yaml(
    tmp_path: Path,
) -> None:
    """`copy_mode` and the per-row `compressed` flag are what an auditor reads to know NOT to
    expect byte identity, so they have to survive YAML — a bool that came back as the string
    "True", or a key the writer dropped, turns the receipt into a guess.

    Read back with the same `packager`/`yaml` pair the gallery reads with, so this pins the file
    rather than the dataclass that produced it.
    """
    folder = compressed_deck(tmp_path)

    document = yaml.safe_load((folder / packager.META_FILE).read_text(encoding="utf-8"))

    assert document["copy_mode"] == "compress"
    rows = document["panel_map"]
    assert [row_["compressed"] for row_ in rows] == [True, True, True]
    assert all(isinstance(row_["compressed"], bool) for row_ in rows), "a bool, not the word"
    assert all(row_["ref_label"] == "" for row_ in rows), "FR-302: nothing was quoted"
    assert all(len(row_["source_text_original"]) > len(row_["source_text"]) for row_ in rows), \
        "both sides of the compression are on the row — FR-309 measures its label off the longer"
    # And the gallery reads exactly these rows: the routing helper keeps every one of them.
    assert len(gallery._panel_rows(document)) == 3


def test_nfr22_the_card_tolerates_a_row_that_predates_the_compressed_key(tmp_path: Path) -> None:
    """An older run's `meta.yaml` has rows with no `compressed` key at all, and its page still has
    to build: the gallery is read on runs that finished weeks ago, and NFR-22 pays for a template
    error with every card on the page. The pre-D54 shape is the fallback, not an error."""
    store_source(tmp_path)
    legacy = row(1, 1, text="Panel one")
    assert "compressed" not in legacy, "the control: this is genuinely the older row shape"
    asset(tmp_path, meta(source_post=source_post(), source_panel_count=1, slide_count=1,
                         panel_map=[legacy]),  # and no `copy_mode` key either
          media=("slide_01.jpg",))

    html_text = page(tmp_path)

    assert html_text.count('<div class="pair">') == 1
    assert "slide 1 ← source panel 1" in html_text
    assert "“Panel one”" in html_text


# ------------------------------- FR-309 as amended (v2.3.0/D54): the three compression labels
#
# A compressed deck reaches this page looking exactly like a quoting one — same three-part card,
# same pairs, same pictures — and the ONE thing an operator must not have to infer is that the
# words beside each source panel are not that panel's words. FR-309's amendment puts that fact on
# three surfaces, at three scales, and each answers a different question:
#
#   header  "how far did this deck's compression have to travel"   -> the LONGEST original
#   chip    "how far did THIS slide's"                             -> that row's own original
#   receipt "what is the receipt for a deck that quoted nothing"   -> the post + the panel map
#
# All three read `source_text_original`, which is why they can never disagree about what counts as
# an original; all three are silent on a verbatim deck and on a pre-D54 `meta.yaml`, which is what
# the tolerance test at the end of this section holds them to.

#: The three `source_text_original` lengths `compressed_deck()` above writes, in row order. Derived
#: rather than typed: the fixture builds its originals by repetition, and a hand-copied 259 here
#: would silently stop matching the day somebody adds a word to the panel it measures.
COMPRESSED_ORIGINALS = [
    len("Panel one. " + "It keeps explaining at length. " * 8),
    len("Panel two. " + "It also explains at length. " * 8),
    len("Panel three. " + "And it explains once more. " * 8),
]


def test_fr309_a_compressed_decks_header_states_the_longest_panel_it_compressed(
    tmp_path: Path,
) -> None:
    """The card's first answer, and the reason it is the LONGEST rather than an average.

    The mode exists because a 1,048-character panel arrived on a style whose declared slide budget
    was 180. An average would hide exactly that panel — the one that made the case — behind two
    short siblings, so the header names the biggest distance travelled. The line sits with the
    other provenance facts and before the creator's own caption, because "these are not this
    post's words" is context for the caption directly under it.
    """
    compressed_deck(tmp_path)

    html_text = page(tmp_path)

    head = html_text.split('<div class="pairs">')[0]
    assert f"Copy: compressed from {max(COMPRESSED_ORIGINALS)} chars" in head
    assert ("our slides are this deck's panels compressed to the style's budget, never quoted "
            "(D54)") in head
    # Order inside the header: the post's facts, its permalink, then the compression note, then
    # the creator's caption. The note is context FOR the caption, so it may not follow it.
    assert head.index("Source deck:") < head.index("Copy: compressed from")
    assert head.index("Copy: compressed from") < head.index("Original caption:")


def test_fr309_each_compressed_tile_states_ITS_OWN_source_length_in_the_source_chip(
    tmp_path: Path,
) -> None:
    """The per-slide answer, in the slot that always carried this row's provenance.

    On a verbatim row that chip reads `source · P1.panel.3` — the label the words were quoted
    under. A compressed row has no label to name (FR-302 as amended gives compressed slides none),
    so the chip carries the compression instead. Same chip, same CSS, one question: how did this
    row's text come to be. Per-row rather than per-deck because a deck whose panels ran 1,048 /
    120 / 1,018 characters compressed three very different distances, and the tile is where an
    operator judges whether THIS one kept its meaning.
    """
    compressed_deck(tmp_path)

    html_text = page(tmp_path)

    chips = re.findall(r'<span class="tag">source[^<]*</span>', html_text)
    assert len(chips) == 3, chips
    for chip, original in zip(chips, COMPRESSED_ORIGINALS):
        assert chip == f'<span class="tag">source · compressed from {original} chars</span>'
    assert "P1.panel." not in html_text, "FR-302: a compressed slide quotes no label to print"


def test_fr309_a_compressed_row_with_no_original_falls_back_to_the_bare_source_chip(
    tmp_path: Path,
) -> None:
    """"Compressed from 0 chars" is a sentence nobody should ever read.

    A dropped panel — empty at source, or blanked by the handle/URL gate — keeps its row and its
    position (that row IS the alignment) and reaches the card with an empty `source_text_original`
    on some paths. The chip then says what it can say and nothing more: `source`, bare, exactly as
    a row with no provenance has always rendered. The DECK-level header is unaffected, because it
    measures the longest original and this row contributes none.
    """
    store_source(tmp_path)
    dropped = compressed_row(2, 2, text="", original="")
    asset(tmp_path, meta(source_post=source_post(), source_panel_count=2, slide_count=2,
                         copy_source_post_id="7412998877", copy_source_refs={},
                         copy_mode="compress",
                         panel_map=[compressed_row(1, 1, text="Ship it.", original="A" * 400),
                                    dropped]),
          media=("slide_01.jpg", "slide_02.jpg"))

    html_text = page(tmp_path)

    chips = re.findall(r'<span class="tag">source[^<]*</span>', html_text)
    assert chips == ['<span class="tag">source · compressed from 400 chars</span>',
                     '<span class="tag">source</span>']
    assert "compressed from 0 chars" not in html_text
    assert "Copy: compressed from 400 chars" in html_text, "the header takes the longest, not 0"
    assert html_text.count('<div class="pair">') == 2, "the dropped row keeps its tile and place"


def test_fr302_a_compressed_decks_receipt_never_claims_a_quote_of_any_kind(
    tmp_path: Path,
) -> None:
    """The receipt is the surface D54 could most easily have broken in silence.

    A compressed deck arrives with a bound post id and an EMPTY `copy_source_refs` — which is
    precisely the shape the "nothing was quoted" branch was built for, and that branch printed
    `Quoted post: <id>` over a deck that quoted nothing from it. The compressed answer is checked
    FIRST, so neither that line nor the `Quotes … verbatim as the …` line can be reached: the claim
    on this card is the post the words were compressed FROM, and the receipt for WHICH words is the
    panel map further down the same card.
    """
    compressed_deck(tmp_path)

    html_text = page(tmp_path)

    assert ("Compressed from post: 7412998877 — see the panel map below for what each slide was "
            "compressed from") in html_text
    assert "Quoted post:" not in html_text
    assert "Quotes" not in html_text and "Also quoted:" not in html_text


def test_fr302_a_compressed_deck_that_somehow_kept_refs_still_never_prints_a_quote_line(
    tmp_path: Path,
) -> None:
    """The mode is answered BEFORE the refs branch, not inside it — so a stray label (an older
    meta, a hand-edit, a future writer that forgets FR-302) cannot resurrect the verbatim receipt
    on a deck whose slides were compressed. The stronger guarantee is worth having because the
    failure it prevents is a card that tells an auditor to expect byte identity that is not
    there."""
    compressed_deck(tmp_path, copy_source_refs={"headline": "P1.hook.2",
                                                "caption": "P1.caption"})

    html_text = page(tmp_path)

    assert "Compressed from post: 7412998877" in html_text
    assert "Quotes P1.hook.2" not in html_text
    assert "Quoted post:" not in html_text and "Also quoted:" not in html_text


def test_fr309_a_verbatim_deck_is_untouched_by_all_three_compression_labels(
    tmp_path: Path,
) -> None:
    """The regression half, and the one that covers the overwhelming majority of runs: verbatim is
    the engine default. The header, the chips and the receipt must all be byte-identical to their
    pre-D54 selves — each of the three is a one-branch addition, and a condition written the wrong
    way round would label every quoting deck as compressed."""
    deck(tmp_path, copy_mode="verbatim")

    html_text = page(tmp_path)

    assert "compressed" not in html_text.lower()
    assert "Copy: compressed from" not in html_text
    assert '<span class="tag">source · P1.panel.1</span>' in html_text, "the label chip is back"
    assert "Quotes P1.panel.1 verbatim as the slide 1 · post 7412998877" in html_text,         "the pre-D54 receipt, unchanged"
    assert "Also quoted: caption P1.caption" in html_text


def test_nfr22_a_pre_d54_meta_renders_the_old_header_chip_and_receipt_without_raising(
    tmp_path: Path,
) -> None:
    """The gallery is read on runs that finished weeks ago, and those `meta.yaml` files have no
    `copy_mode` key and no `compressed` key on any row. All three labels must answer "there is no
    compression here" from ABSENT data rather than from a False — a `KeyError` in a template costs
    NFR-22 the whole page, not one card, and a truthy read of a missing key would label every
    archived deck as compressed."""
    store_source(tmp_path)
    legacy = row(1, 1, text="Panel one")
    assert "compressed" not in legacy and "source_text_original" not in legacy, \
        "the control: this really is the pre-D54 row shape"
    document = meta(source_post=source_post(), source_panel_count=1, slide_count=1,
                    copy_source_post_id="7412998877", panel_map=[legacy])
    assert "copy_mode" not in document, "…and the document really has no mode key at all"
    asset(tmp_path, document, media=("slide_01.jpg",))

    html_text = page(tmp_path)

    assert "compressed" not in html_text.lower()
    assert '<span class="tag">source · P1.panel.1</span>' in html_text
    assert "Quoted post: 7412998877" in html_text
    assert gallery._compressed_from(document) == 0
    assert gallery._row_original(legacy) == 0


def test_the_header_and_the_tile_measure_read_the_same_originals(tmp_path: Path) -> None:
    """One reader, two scales — asserted as an identity rather than trusted.

    `_compressed_from` is `max(_row_original(...))`, so the header can never name a length no tile
    shows, and no tile can show one the header did not consider. That is the whole reason the
    per-row reading was extracted: two independent length rules over the same rows is how a card
    ends up saying "compressed from 1,048 chars" over three tiles that each say 259.

    **RE-BASED at D62/FR-354: the ROWS are the authority, not `copy_mode`.** This test used to arm
    the measure by flipping the document's mode to `verbatim` and expecting 0. That was correct
    while a deck was compressed all the way or not at all — and `copy_mode: auto` ends it. Under
    `auto` a deck compresses only the panels that overflowed their budget, so one document holds
    both kinds of row by design; a card that read the MODE would print "Compressed from post" over
    quoted rows and nothing over compressed ones, which is wrong in both directions on the same
    card. So the flip below now asserts the opposite property — the mode moves nothing — and the
    rows' own `compressed` flags are what the header answers from.
    """
    compressed_deck(tmp_path)
    document = yaml.safe_load(
        (tmp_path / "0001_carousel_linkedin" / packager.META_FILE).read_text(encoding="utf-8"))

    per_row = [gallery._row_original(row_) for row_ in gallery._panel_rows(document)]

    assert per_row == COMPRESSED_ORIGINALS
    assert gallery._compressed_from(document) == max(per_row)
    # The deck-level mode is NOT what arms it: an `auto` deck is mixed by design (FR-354), so a
    # document whose rows still claim compression measures exactly the same under any mode string.
    for mode in ("verbatim", "auto", "compress"):
        document["copy_mode"] = mode
        assert gallery._compressed_from(document) == max(per_row), \
            f"the mode moved the measure at copy_mode: {mode}"
    # …and clearing the ROWS' own claims is what silences it, whatever the mode says.
    for row_ in document["panel_map"]:
        row_["compressed"] = False
    assert gallery._compressed_from(document) == 0
    assert gallery._any_compressed(document) is False

# ------------------------------------- FR-337 (v2.4.0/D56): which ALGORITHM chose this style
#
# The card has named the style key since FR-76. What D56 added is the OTHER half of the question an
# operator asks in front of a batch: not only "which look is this" but "who chose it, and why".
# Matched assignment is an overlay on the FR-291 rotation, so both algorithms are live in one run
# and a card that annotated neither would leave the operator unable to tell a deliberate match from
# a content-blind default.
#
# Three properties, and each is a PRD-driven choice rather than a formatting preference:
#
# * the badge vocabulary is fixed at `matched` / `rotation`, and `rotation_fallback` deliberately
#   prints as plain `rotation` — the PICK on that card genuinely IS the FR-291 baseline, and the
#   `style match degraded` tag beside it carries the distinction that the matcher never spoke;
# * `style_reason` and `style_wanted` are MODEL-AUTHORED strings that reach an HTML page, so both
#   go through the one `html.escape` this module uses for every string it reads off disk;
# * a `meta.yaml` written before v2.4.0 carries none of these keys and must render exactly as it
#   always did — no origin invented, no note printed.


def badges(html_text: str) -> list[str]:
    """The identity chips (`<span class="badge">`), in the order the card prints them."""
    return re.findall(r'<span class="badge">([^<]+)</span>', html_text)


def test_fr337_a_matched_pick_names_the_algorithm_and_the_fit_it_claimed(tmp_path: Path) -> None:
    """`style: X · matched/high` — the badge an operator scans a page of cards with.

    `medium` prints identically to `high` on purpose: a `medium` answer was ACCEPTED by the matcher
    (a decent fit is a fit), so the card states the fit and lets the operator judge it rather than
    flagging one of the two as a problem. The reason line under the badges is where the model's own
    sentence lands, and it is `prov` rather than `note` because it is provenance — it explains a
    decision that was already taken, and asks for nothing.
    """
    deck(tmp_path, asset_id="0001_carousel_linkedin", style_key="icon-ledger-carousel",
         style_origin="matched", style_fit="high",
         style_reason="seven dense labelled panels suit a numbered ledger deck")
    deck(tmp_path, asset_id="0002_carousel_linkedin", style_key="circuit-atlas-dark",
         style_origin="matched", style_fit="medium",
         style_reason="benchmark tables, close enough to a diagram deck")

    html_text = page(tmp_path)

    chips = badges(html_text)
    assert "style: icon-ledger-carousel · matched/high" in chips
    assert "style: circuit-atlas-dark · matched/medium" in chips, \
        "an accepted `medium` reads exactly like `high`; the operator judges the difference"
    assert "Style match: seven dense labelled panels suit a numbered ledger deck" in html_text
    assert "Wanted archetype" not in html_text, "nothing was wanted — nothing asks for an action"


def test_fr337_a_low_fit_keeps_its_number_and_asks_for_the_style_it_could_not_find(
    tmp_path: Path,
) -> None:
    """The other accepted outcome: the matcher answered, the answer was "nothing here fits", and the
    FR-291 baseline rendered the card.

    Both halves are on the card because either alone would mislead. `rotation/low` says the pick was
    the deterministic default AND that a real judgement stands behind that; the wanted-archetype
    note says WHICH style the registry is missing. D56 decision 3 is the reason the note exists at
    all — the engine never synthesizes a style at runtime (that would break FR-295's registry
    authority), so a miss is written down and the operator authors the missing style deliberately.
    """
    deck(tmp_path, style_key="letterpress-print-carousel-teal", style_origin="rotation",
         style_fit="low", style_reason="no enabled style renders a social screenshot",
         style_wanted="social screenshot card")

    html_text = page(tmp_path)

    assert "style: letterpress-print-carousel-teal · rotation/low" in badges(html_text)
    assert "Wanted archetype: social screenshot card" in html_text
    assert "author one to close the gap (FR-337)" in html_text, "the note asks for an action"
    assert 'class="note"' in html_text, "it is a call to action, not provenance"


def test_fr337_a_rotation_fallback_prints_as_plain_rotation_beside_the_degraded_tag(
    tmp_path: Path,
) -> None:
    """The deliberate collapse in the badge vocabulary, pinned because it looks like a bug.

    `_ORIGIN_LABELS` maps `rotation_fallback` to `rotation`, so a card whose matcher call never
    came back is annotated exactly like a card the matcher declined. That is correct and it is a
    PRD choice: the PICK on both cards IS the FR-291 baseline, which is what this annotation names,
    and annotating them differently would suggest a different STYLE was rendered. The distinction
    that actually matters — the matcher never spoke — is carried by the `style match degraded`
    badge beside it, which `generate._record` attaches from `style_origin` and the FR-73 badge loop
    prints without knowing anything about styles.

    So the two vocabularies are asserted TOGETHER: the word `rotation_fallback` must never reach a
    card, and the degradation badge must be there to say what the collapsed word left out.
    """
    deck(tmp_path, style_key="anime-noir-statement", style_origin="rotation_fallback",
         degradations=[DegradationTag.STYLE_MATCH_DEGRADED.value])

    html_text = page(tmp_path)

    assert "style: anime-noir-statement · rotation" in badges(html_text)
    # Scoped to the CARDS, not to the document: the page title is the run folder's name, which is
    # this test function's name under `tmp_path` and therefore carries the word by construction.
    cards = "".join(re.findall(r"<article.*?</article>", html_text, re.S))
    assert cards, "the fixture must actually produce a card for this to mean anything"
    assert "rotation_fallback" not in cards, \
        "the card names the PICK's algorithm; the tag names what failed"
    assert '<span class="badge warn">style match degraded</span>' in html_text
    assert DegradationTag.STYLE_MATCH_DEGRADED.value in [tag.value for tag in DegradationTag], \
        "the tag is FR-73 vocabulary, so the badge loop finds it with no change here"


def test_fr337_the_two_model_authored_style_strings_are_html_escaped(tmp_path: Path) -> None:
    """`style_reason` and `style_wanted` are written by a MODEL, travel through `PlanEntry` and
    `meta.yaml`, and land in HTML. That is a three-hop path from a language model to a page the
    operator opens in a browser, so both go through the same `html.escape` every other
    read-from-disk string here does — there is one escaping mechanism in this module and no card is
    entitled to a second one.

    Asserted on the two shapes that matter: a `<script>` open tag (the injection an escape exists
    to defuse) and a bare `&`/quote pair (the ordinary case that would produce invalid markup and
    a silently mangled sentence). The raw strings must appear NOWHERE, escaped or not, as tags.
    """
    deck(tmp_path,
         style_key="social-quote-card", style_origin="rotation", style_fit="low",
         style_reason='<script>alert("xss")</script> & "quoted" prose',
         style_wanted="<b>listicle</b> & co")

    html_text = page(tmp_path)

    assert "<script" not in html_text, "an escaped page has no script tag of any origin"
    assert "&lt;script&gt;" in html_text and "&amp;" in html_text
    assert "&lt;b&gt;listicle&lt;/b&gt;" in html_text, "the wanted note is escaped too"
    assert "<b>listicle</b>" not in html_text
    # …and the escaping does not eat the sentence: what survives is readable prose.
    assert "quoted" in html_text and "prose" in html_text


def test_fr337_a_reason_that_arrived_with_newlines_is_collapsed_onto_one_line(
    tmp_path: Path,
) -> None:
    """Both lines are whitespace-collapsed before they are escaped, because a model-authored string
    that arrived with a newline in it would otherwise open a two-line hole in a one-line slot and
    the card would stop reading as a row of facts."""
    deck(tmp_path, style_origin="matched", style_fit="high",
         style_reason="dense labelled rows\n\n   suit a ledger deck",
         style_wanted="listicle\ndeck")

    html_text = page(tmp_path)

    assert "Style match: dense labelled rows suit a ledger deck" in html_text
    assert "Wanted archetype: listicle deck" in html_text


def test_fr337_a_pre_v240_meta_prints_the_bare_style_label_and_no_match_lines(
    tmp_path: Path,
) -> None:
    """NFR-22's oldest rule applied to the newest fields: this module READS documents off disk,
    including ones written by earlier versions of this engine.

    A `meta.yaml` from two weeks ago carries no `style_origin`, no `style_fit`, no `style_reason`
    and no `style_wanted` — so the card shows what those cards have always shown, a bare
    `style: X`, and invents no origin for a run that recorded none. The same silence covers every
    `assignment: rotation` run and every override brief, all of which carry the same empty strings
    and mean the same thing by them.
    """
    document = meta(asset_id="0001_carousel_linkedin", style_key="editorial-voxel-carousel")
    for key in ("style_origin", "style_fit", "style_reason", "style_wanted"):
        assert key not in document, f"the pre-v2.4.0 fixture must not carry {key}"
    asset(tmp_path, document, media=("slide_01.jpg",))

    html_text = page(tmp_path)

    assert "style: editorial-voxel-carousel" in badges(html_text)
    assert not any("·" in chip and chip.startswith("style:") for chip in badges(html_text)), \
        "no origin was recorded, so none is printed"
    assert "Style match:" not in html_text and "Wanted archetype" not in html_text


def test_fr337_an_override_brief_still_shows_its_bare_brief_override_label(tmp_path: Path) -> None:
    """M14: an override brief's style channel is suppressed outright, so it is never matched and
    never rotated — `generate._record` writes `brief_override` as the key and the four provenance
    fields stay empty. The card says so with the same bare label a pre-v2.4.0 meta gets, because it
    is the same fact: no algorithm chose this look, a brief did."""
    asset(tmp_path, meta(asset_id="0001_image_linkedin", creative_format="image",
                         style_key="brief_override", style_origin="rotation", slide_count=0),
          media=("image.jpg",))

    html_text = page(tmp_path)

    assert "style: brief_override · rotation" in badges(html_text), \
        "the runner stamps `rotation` on every live entry, including the ones it never styled"
    assert "Style match:" not in html_text, "no matcher answer, so no reason line"
    assert "Wanted archetype" not in html_text


def test_fr75_the_match_provenance_lines_add_no_remote_byte_to_the_page(tmp_path: Path) -> None:
    """The self-containment guarantee, re-asserted over the FIELDS D56 added.

    A model-authored string is exactly the shape that could smuggle a URL onto an offline page — and
    a page that fetches one thing is no longer a page an operator can review on a plane. So the
    reason and the wanted note are given a URL each, and neither may become anything a browser
    loads.

    **Measured, and narrower than the sibling test above.**
    `test_fr75_the_only_remote_string_on_the_page_is_a_permalink_nobody_has_to_load` asserts that
    every `http` string on the page sits inside an `<a href>`. That holds for every string the
    ENGINE writes, and it does not hold for model prose: a URL inside `style_reason` renders as
    escaped plain text in a `<p class="prov">`. Which is fine, and is what this test pins — a bare
    text URL is inert (no browser auto-links one), so FR-75's actual guarantee is intact: nothing on
    the page is fetched. The assertion is therefore made where the guarantee lives, on the
    ATTRIBUTES a browser acts on, rather than on the presence of the characters `http` anywhere in
    the document. If the model-text URL is ever considered noise worth stripping, that is a change
    to `gallery._style_html`, and this test is where it would be re-based.
    """
    deck(tmp_path, virlo_url=PERMALINK, style_origin="rotation", style_fit="low",
         style_reason="see https://evil.test/track.gif for why",
         style_wanted="card like https://evil.test/style.png")

    html_text = page(tmp_path)

    assert all(src.startswith("./") for src in media_srcs(html_text)), media_srcs(html_text)
    assert not any("evil.test" in src for src in media_srcs(html_text)), \
        "a model-authored URL is never a fetch"
    hrefs = re.findall(r'href="([^"]*)"', html_text)
    assert {href for href in hrefs if not href.startswith("./")} == {PERMALINK}, \
        f"the permalink is the only REMOTE link on the page: {hrefs}"
    assert not any("evil.test" in href for href in hrefs), \
        "model prose must never become something the operator can click by accident"
    assert "<script" not in html_text and "<link" not in html_text and "@import" not in html_text
    # The URLs ARE on the page — as inert escaped text inside the two provenance paragraphs, which
    # is the honest rendering of what the matcher said and loads nothing.
    assert "Style match: see https://evil.test/track.gif for why" in html_text


# ------------------------------------------- FR-351 (v2.6.0/D62): the cover-candidate strip
#
# The cover is the frame every other slide copies, and D62 buys two or three of them and keeps the
# ones it turned down. The strip is where the operator gets to disagree with the pick — a choice
# they cannot see is a choice they cannot audit, and "the model always takes the darkest cover" is
# a habit that only shows up across a batch.
#
# Four properties, and each is a decision rather than a formatting preference:
#
# * it is SILENT on everything that never fanned out — a `cover_candidates: 1` run, an image, a
#   reel, and every `meta.yaml` written before v2.6.0, which carry no `cover_pick` key at all. A
#   strip of one thumbnail shows a comparison that never happened;
# * the CHOSEN tile is marked by the candidate's own id, parsed off its file name, not by its
#   position in the list — a deck whose candidate 2 never landed keeps files `1` and `3`, and
#   counting positions would outline the wrong picture on exactly the runs worth looking at;
# * the reason line is MODEL-AUTHORED text landing in HTML, so it is escaped and collapsed like
#   every other string this module reads off disk;
# * NFR-22 tolerance: a malformed receipt, a remote URL, a traversal or a file that is not on disk
#   each drop out silently. One bad thumbnail may never cost the page.


def cover_files(run: Path, asset_id: str = "0001_carousel_linkedin", *numbers: int) -> None:
    """Write the kept cover candidates a fanned-out deck leaves under `<asset>/covers/`."""
    folder = run / asset_id / "covers"
    folder.mkdir(parents=True, exist_ok=True)
    for number in numbers:
        (folder / f"cover_candidate_{number}.jpg").write_bytes(JPEG)


def cover_pick(chosen: int = 2, *numbers: int, reason: str = "the cleanest type hierarchy",
               degraded: bool = False) -> dict[str, Any]:
    """One `meta.yaml.cover_pick` receipt in the shape `carousel.package()` writes it (FR-351)."""
    return {"candidates": [f"covers/cover_candidate_{number}.jpg" for number in numbers],
            "chosen": chosen, "reason": reason, "degraded": degraded}


def figures(html_text: str) -> list[str]:
    """Every `<figure …>` opening tag on the page — the strip's tiles, chosen class included."""
    return re.findall(r"<figure[^>]*>", html_text)


def test_fr351_the_strip_draws_every_candidate_and_outlines_the_one_that_anchored(
    tmp_path: Path,
) -> None:
    """Three thumbnails, one of them marked, plus the pick's own words underneath.

    The chosen tile has to be legible as chosen without reading the reason line — an outline and a
    caption, not colour alone — because the operator is scanning a batch of cards and the question
    "which of these shipped" must not need a second look.
    """
    cover_files(tmp_path, "0001_carousel_linkedin", 1, 2, 3)
    document = meta(cover_pick=cover_pick(2, 1, 2, 3))
    asset(tmp_path, document, media=("slide_01.jpg",))

    html_text = page(tmp_path)

    assert html_text.count("<figcaption>") == 3
    assert figures(html_text) == ["<figure>", '<figure class="chosen">', "<figure>"]
    assert "cover 2 · chosen" in html_text
    assert "cover 1</figcaption>" in html_text and "cover 3</figcaption>" in html_text
    assert "Cover pick: the cleanest type hierarchy" in html_text
    assert "./0001_carousel_linkedin/covers/cover_candidate_2.jpg" in media_srcs(html_text)
    assert "cover_pick_degraded" not in html_text


def test_fr351_the_chosen_tile_is_found_by_candidate_id_and_not_by_list_position(
    tmp_path: Path,
) -> None:
    """The gap case, which is the whole reason the id is parsed off the file name.

    A deck whose candidate 2 never landed keeps `cover_candidate_1` and `cover_candidate_3`, and
    the pick names 3. Reading `chosen` as a 1-based index into the surviving list would outline
    candidate 1's thumbnail and caption it "chosen" — a page that says the wrong render anchored
    the deck, on precisely the runs where knowing that matters.
    """
    cover_files(tmp_path, "0001_carousel_linkedin", 1, 3)
    asset(tmp_path, meta(cover_pick=cover_pick(3, 1, 3)), media=("slide_01.jpg",))

    html_text = page(tmp_path)

    assert figures(html_text) == ["<figure>", '<figure class="chosen">']
    assert "cover 3 · chosen" in html_text
    assert "cover 1 · chosen" not in html_text


def test_fr351_a_degraded_pick_says_so_under_the_strip(tmp_path: Path) -> None:
    """The fail-open path, stated on the page: candidate 1 anchored because nobody could judge.

    The note carries the tag's own spelling, so it and the `cover_pick_degraded` badge above it
    read as one fact rather than two — and it names the candidate the receipt actually recorded,
    because a deck that lost candidate 1 outright defaults to the first that landed.
    """
    cover_files(tmp_path, "0001_carousel_linkedin", 1, 2)
    document = meta(cover_pick=cover_pick(1, 1, 2, reason="cover_pick_degraded: the call raised",
                                          degraded=True),
                    degradations=[DegradationTag.COVER_PICK_DEGRADED.value])
    asset(tmp_path, document, media=("slide_01.jpg",))

    html_text = page(tmp_path)

    assert "cover_pick_degraded — candidate 1 anchored by default" in html_text
    assert 'class="prov degraded"' in html_text
    assert "Cover pick: cover_pick_degraded: the call raised" in html_text
    assert figures(html_text) == ['<figure class="chosen">', "<figure>"]


def test_fr351_no_strip_without_a_real_comparison_to_show(tmp_path: Path) -> None:
    """Silent on every deck that did not fan out — including a fan-out where one cover landed.

    Three documents, three different ways of meaning "there was no choice here", and all three
    must render exactly as they did before this strip existed: no `cover_pick` key at all (the
    whole pre-v2.6.0 world and every `cover_candidates: 1` run), a receipt with a single candidate
    (two were bought, one came back), and a malformed receipt (NFR-22 — a page that raises costs
    the operator every card, not one thumbnail).
    """
    for asset_id, pick in (("0001_carousel_linkedin", None),
                           ("0002_carousel_linkedin", cover_pick(1, 1)),
                           ("0003_carousel_linkedin", ["not", "a", "mapping"])):
        cover_files(tmp_path, asset_id, 1)
        document = meta(asset_id=asset_id, media=())
        if pick is not None:
            document["cover_pick"] = pick
        asset(tmp_path, document, media=("slide_01.jpg",))

    html_text = page(tmp_path)

    assert "<figcaption>" not in html_text and "Cover pick:" not in html_text
    assert 'class="covers"' not in html_text
    assert html_text.count('class="card') == 3, "all three cards still render"


def test_fr351_a_candidate_path_that_is_not_a_local_file_is_dropped(tmp_path: Path) -> None:
    """FR-75 again, at the last step: nothing on this page may fetch a remote byte.

    A receipt is written by this engine, so these shapes should be impossible — but the page is
    also read on runs produced by other builds, and one absolute URL turns the offline artifact
    into a page that phones out. A traversal, a drive letter and a path with no file behind it are
    dropped for the same reason a missing panel image is: the tile is simply not drawn.
    """
    cover_files(tmp_path, "0001_carousel_linkedin", 1, 2)
    document = meta(cover_pick={
        "candidates": ["https://cdn.example.test/cover.jpg", "covers/cover_candidate_1.jpg",
                       "../../etc/passwd", "C:/Windows/cover.jpg", "covers/never_written.jpg",
                       "covers/cover_candidate_2.jpg"],
        "chosen": 2, "reason": "the widest margins", "degraded": False})
    asset(tmp_path, document, media=("slide_01.jpg",))

    html_text = page(tmp_path)

    assert figures(html_text) == ["<figure>", '<figure class="chosen">'], \
        "only the two real local files survive, and the chosen id still finds its tile"
    assert "cdn.example.test" not in html_text and "passwd" not in html_text
    assert all(src.startswith("./") for src in media_srcs(html_text))


def test_fr351_the_pick_reason_is_escaped_like_every_other_model_authored_string(
    tmp_path: Path,
) -> None:
    """`reason` is written by a model and lands in HTML, so it is collapsed and escaped.

    The same rule `_style_html` applies to the matcher's reason, for the same two failures: a
    newline would open a hole in a one-line slot, and a `<script>` would stop being text.
    """
    cover_files(tmp_path, "0001_carousel_linkedin", 1, 2)
    asset(tmp_path, meta(cover_pick=cover_pick(
        1, 1, 2, reason="best\n contrast <script>alert('x')</script> & the widest margins")),
        media=("slide_01.jpg",))

    html_text = page(tmp_path)

    assert "<script>" not in html_text
    assert "Cover pick: best contrast &lt;script&gt;" in html_text
    assert "&amp; the widest margins" in html_text


# ------------------------------------------------- FR-346 (v2.7.0, D63): translation provenance
#
# A translated deck reaches this page with the same two absences a compressed one has — no
# `ref_label` on any row and nothing in `copy_source_refs`, because the walk clears them (a label
# pointing at bytes we did not ship would be a false receipt) — plus two facts no deck before it
# carried: `copy_language: target` with a `source_language` code at the top of `meta.yaml`, and
# `translated: true` on the rows whose text is the model's translation.
#
# The axes are ORTHOGONAL and the tests below keep proving it: `copy_mode` answers how LONG the
# words are, `copy_language` answers what TONGUE they are in, and under copy mode auto one row can
# be both. Every reading is per ROW for the same reason D62 made compression per row — a mixed
# deck is the normal shape, and a deck-level answer would mislabel half of it.


def translated_row(slide: int, position: int, *, text: str = "", original: str = "",
                   brief: str = "", image: str | None = "", compressed: bool = False,
                   translated: bool = True) -> dict[str, Any]:
    """One `panel_map` row as `copywrite._translated_deck` writes it (D63/FR-343).

    `ref_label` empty (nothing was quoted), `translated` True where the translation shipped, and
    `source_text_original` carrying the SOURCE panel the model read. `compressed=True` is the auto
    -mode row that was translated and THEN fitted to the style's budget — the one row shape that
    has to carry both answers at once.
    """
    built = row(slide, position, text=text, label="", brief=brief, image=image)
    built["ref_label"] = ""
    built["translated"] = translated
    built["compressed"] = compressed
    built["source_text_original"] = original or text
    return built


def translated_deck(run: Path, **overrides: Any) -> Path:
    """The standard three-panel deck, written as a TARGET-language run writes it."""
    store_source(run)
    document = meta(
        source_post=source_post(), source_panel_count=3, slide_count=3,
        copy_source_post_id="7412998877",
        copy_source_refs={},  # the walk clears every label — nothing here was quoted
        copy_mode="verbatim", copy_language="target", source_language="de",
        panel_map=[
            translated_row(1, 1, text="Ship it, then measure.",
                           original="Liefere es aus, dann miss nach.",
                           brief="hero image, heading centred"),
            translated_row(2, 2, text="Measure it, then cut.",
                           original="Miss nach, dann kuerze.",
                           brief="two-column table, four rows"),
            translated_row(3, 3, text="Cut it, then ship again.",
                           original="Kuerze es, dann liefere erneut.",
                           brief="line chart, three series")])
    document.update(overrides)
    return asset(run, document, media=("slide_01.jpg", "slide_02.jpg", "slide_03.jpg"))


def test_fr346_a_translated_decks_header_says_which_language_the_panels_were_read_from(
    tmp_path: Path,
) -> None:
    """The card's language answer, beside the length answer and never instead of it.

    "These are not this post's words" is context for the creator's own caption directly under it —
    the same argument that put D54's compression note there — and it is the one thing that makes
    the side-by-side strip legible: the source tiles are in German and ours are not, which without
    this line reads as a rendering that ignored its source.
    """
    translated_deck(tmp_path)

    html_text = page(tmp_path)

    head = html_text.split('<div class="pairs">')[0]
    assert ("Copy: translated from de to the platform's language — our slides are this deck's "
            "panels translated, never shortened (D63)") in head
    assert head.index("Source deck:") < head.index("Copy: translated from de")
    assert head.index("Copy: translated from de") < head.index("Original caption:")
    assert "Copy: compressed from" not in head, "nothing was compressed on this deck"


def test_fr346_each_translated_tile_says_which_language_it_came_out_of(tmp_path: Path) -> None:
    """The per-slide answer, in the slot that has always carried this row's provenance.

    On a verbatim row that chip reads `source · P1.panel.3`, on a compressed row `compressed from
    N chars`; a translated row has no label to name and carries the language instead. Same chip,
    same CSS, one question: how did this row's text come to be.
    """
    translated_deck(tmp_path)

    html_text = page(tmp_path)

    chips = re.findall(r'<span class="tag">source[^<]*</span>', html_text)
    assert chips == ['<span class="tag">source · translated from de</span>'] * 3
    assert "P1.panel." not in html_text, "a translated slide quotes no label to print"


def test_fr346_a_row_that_was_translated_and_then_compressed_prints_both_chips(
    tmp_path: Path,
) -> None:
    """Copy mode auto's mixed deck, on both axes at once (FR-353 + FR-343).

    Row 1 was translated and then fitted to the style's budget, row 2 was translated and fitted
    inside it, row 3 kept its source language entirely (its panel was already English). Three
    different rows, three different chips, and the compression is named FIRST because that is the
    order the two transforms happened in.
    """
    store_source(tmp_path)
    document = meta(
        source_post=source_post(), source_panel_count=3, slide_count=3,
        copy_source_post_id="7412998877", copy_source_refs={},
        copy_mode="auto", copy_language="target", source_language="de",
        panel_map=[
            translated_row(1, 1, text="Ship it.", original="Liefere es aus, " * 20,
                           compressed=True),
            translated_row(2, 2, text="Measure it.", original="Miss nach."),
            translated_row(3, 3, text="Already English here.", translated=False)])
    asset(tmp_path, document, media=("slide_01.jpg", "slide_02.jpg", "slide_03.jpg"))

    html_text = page(tmp_path)

    chips = re.findall(r'<span class="tag">source[^<]*</span>', html_text)
    assert chips == [
        f'<span class="tag">source · compressed from {len("Liefere es aus, " * 20)} chars · '
        "translated from de</span>",
        '<span class="tag">source · translated from de</span>',
        '<span class="tag">source</span>']
    head = html_text.split('<div class="pairs">')[0]
    assert "Copy: compressed from" in head and "Copy: translated from de" in head, \
        "the card states both transforms too — one is not a qualifier on the other"


def test_fr346_the_receipt_of_a_translated_deck_never_claims_it_quoted_the_post(
    tmp_path: Path,
) -> None:
    """The trap D54 already fell into once, one axis over.

    A translated deck arrives with a bound post id and no refs, which is exactly the shape the
    "nothing was quoted" branch prints `Quoted post: <id>` over — and "quoted" over a deck whose
    slides are in a language that post never used is the worst sentence this card could print.
    """
    translated_deck(tmp_path)

    html_text = page(tmp_path)

    assert ("Translated from post: 7412998877 (written in de) — see the panel map below for the "
            "panel each slide was translated from") in html_text
    assert "Quoted post" not in html_text and "Quotes " not in html_text
    assert "Compressed from post" not in html_text


def test_fr346_a_translated_and_compressed_receipt_names_both_in_one_line(
    tmp_path: Path,
) -> None:
    """One receipt for one deck, never two lines arguing about which transform happened."""
    translated_deck(tmp_path, copy_mode="auto",
                    panel_map=[translated_row(1, 1, text="Ship it.", original="Liefere es aus.",
                                              compressed=True)])

    html_text = page(tmp_path)

    assert ("Translated from post: 7412998877 (written in de) — see the panel map below for the "
            "panel each slide was translated from; the panels over the style's budget were then "
            "compressed") in html_text


def test_fr346_a_pre_d63_document_renders_exactly_as_it_did_before(tmp_path: Path) -> None:
    """NFR-22's tolerance, the same one `_any_compressed` owes pre-D54 documents.

    An older `meta.yaml` has no `copy_language`, no `source_language` and no `translated` key on
    any row. Every language surface must answer "there is nothing to say here" — not "translated
    from ", not an empty chip suffix, and above all not a `Translated from post` receipt over a
    deck that quoted its post verbatim.
    """
    store_source(tmp_path)
    legacy = row(1, 1, text="Panel one", brief="hero image")
    asset(tmp_path, meta(source_post=source_post(), source_panel_count=1, slide_count=1,
                         copy_source_post_id="7412998877",
                         copy_source_refs={"slide_1": "P1.panel.1"},
                         panel_map=[legacy]), media=("slide_01.jpg",))

    document = yaml.safe_load((tmp_path / "0001_carousel_linkedin"
                               / packager.META_FILE).read_text(encoding="utf-8"))
    html_text = page(tmp_path)

    assert "copy_language" not in document and "translated" not in document["panel_map"][0]
    assert "translated" not in html_text
    assert "Copy: translated" not in html_text
    assert '<span class="tag">source · P1.panel.1</span>' in html_text


def test_fr346_the_two_new_degradation_tags_ride_the_existing_badge_loop(
    tmp_path: Path,
) -> None:
    """FR-73's single vocabulary: the badge loop walks `DegradationTag`, so a new tag needs no
    schema change and no new branch. Asserted rather than assumed, because "the loop already
    handles it" is the sentence under every tag that turned out not to render."""
    translated_deck(tmp_path, degradations=["copy_not_translated", "translate_length_drift"])

    html_text = page(tmp_path)

    assert '<span class="badge warn">copy not translated</span>' in html_text
    assert '<span class="badge warn">translate length drift</span>' in html_text
    assert {DegradationTag.COPY_NOT_TRANSLATED.value,
            DegradationTag.TRANSLATE_LENGTH_DRIFT.value} <= {tag.value for tag in DegradationTag}


def test_fr346_the_language_facts_reach_the_page_from_the_writer_that_actually_writes_them(
    tmp_path: Path,
) -> None:
    """The loop the fabricated documents above cannot close: FIELD NAMES, end to end (D63).

    `CopyProvenance.copy_language`/`.source_language` -> `generate._record` -> `AssetRecord` ->
    `packager`'s serializer -> `meta.yaml` -> this page, plus the per-row `translated` flag, which
    reaches the document only because `generate._panel_map` copies the copy stage's row key by key
    instead of rebuilding it from a fixed list. A rename anywhere along that chain would leave
    every hand-written test here internally consistent and the real page silent.
    """
    from datetime import datetime, timezone

    from hypesocials import generate
    from hypesocials.config import Config
    from hypesocials.copywrite import CopyProvenance
    from hypesocials.models import PlanEntry, SourcePost, TrendItem

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
                              caption="die fuenf Tools, die ich wirklich nutze",
                              published_at=datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc))])},
        copy_provenance={entry.asset_id: CopyProvenance(
            post_id="7412998877", refs={}, source_panel_count=2,
            copy_language="target", source_language="de",
            panel_map=[{"slide": 1, "source_position": 1, "source_text": "Panel one",
                        "source_text_original": "Tafel eins", "ref_label": "",
                        "compressed": False, "translated": True},
                       {"slide": 2, "source_position": 2, "source_text": "Panel two",
                        "source_text_original": "Tafel zwei", "ref_label": "",
                        "compressed": False, "translated": True}])},
        slide_intel={})
    folder = packager.AssetFolder(tmp_path, generate._record(entry, env))
    (folder.path / "slide_01.jpg").write_bytes(JPEG)
    (folder.path / "slide_02.jpg").write_bytes(JPEG)
    folder.finish()

    document = yaml.safe_load((folder.path / packager.META_FILE).read_text(encoding="utf-8"))
    html_text = page(tmp_path)

    assert document["copy_language"] == "target" and document["source_language"] == "de"
    assert [r["translated"] for r in document["panel_map"]] == [True, True], \
        "`_panel_map` copies the whole row — a fixed key list would have dropped this"
    assert "Copy: translated from de to the platform's language" in html_text
    assert "Translated from post: 7412998877 (written in de)" in html_text
    assert '<span class="tag">source · translated from de</span>' in html_text


def test_fr346_a_source_mode_record_still_says_source_and_prints_nothing_new(
    tmp_path: Path,
) -> None:
    """The regression half of the writer test above: a deck that translated nothing writes
    `copy_language: source`, and `source_language` still records what language it IS in — that is
    the whole point of recording the ladder's answer in BOTH modes (FR-73 as amended)."""
    from hypesocials import generate
    from hypesocials.config import Config
    from hypesocials.copywrite import CopyProvenance
    from hypesocials.models import PlanEntry

    entry = PlanEntry(order=0, asset_id="0001_carousel_linkedin", creative_format="carousel",
                      platform="linkedin", language="en", aspect_ratio="1:1", slide_count=1,
                      source_post_id="7412998877")
    env = generate.Env(config=Config(), run_dir=tmp_path, engine=None, budget=None, log=None,
                       ledger=None, trends={},
                       copy_provenance={entry.asset_id: CopyProvenance(
                           post_id="7412998877", source_language="en",
                           panel_map=[{"slide": 1, "source_position": 1,
                                       "source_text": "Panel one", "ref_label": "P1.panel.1",
                                       "compressed": False, "translated": False}])},
                       slide_intel={})
    folder = packager.AssetFolder(tmp_path, generate._record(entry, env))
    (folder.path / "slide_01.jpg").write_bytes(JPEG)
    folder.finish()

    document = yaml.safe_load((folder.path / packager.META_FILE).read_text(encoding="utf-8"))
    html_text = page(tmp_path)

    assert document["copy_language"] == "source" and document["source_language"] == "en"
    assert document["panel_map"][0]["translated"] is False
    assert "Copy: translated" not in html_text
    assert "Translated from post" not in html_text


def test_fr346_a_creative_with_no_copy_provenance_at_all_defaults_to_source(
    tmp_path: Path,
) -> None:
    """An override brief, an image, a degrade path that produced no provenance: `_record` writes
    the dataclass defaults rather than reaching for a run-level key, so a target-mode run's image
    says `source` — which is true, since translation never reached it (FR-345)."""
    from hypesocials import generate
    from hypesocials.config import Config
    from hypesocials.models import PlanEntry

    entry = PlanEntry(order=0, asset_id="0001_image_linkedin", creative_format="image",
                      platform="linkedin", language="en", aspect_ratio="1:1")
    env = generate.Env(config=Config(), run_dir=tmp_path, engine=None, budget=None, log=None,
                       ledger=None, trends={}, copy_provenance={}, slide_intel={})

    built = generate._record(entry, env)

    assert built.copy_language == "source" and built.source_language == ""
