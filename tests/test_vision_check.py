"""What a frame was ORDERED to carry, and the retry that may not trim a quote (FR-105/FR-322).

`vision_check.check()` — the FR-105 single-shot gate — is DELETED (v2.2.0/D49) and replaced by the
three-critic gauntlet, so the tests that recorded its carrier turn went with it: the expected text
now reaches a model through `gauntlet._expected_blocks`, which `tests/test_gauntlet.py` owns. What
survives here is what survives in the module: the pure helpers that answer "what was this asset
ordered to say" and "how does a re-render differ from the first attempt".

The defect these were written against still binds. A 131-character mapped panel came back as a
53-character mid-sentence stub on 2026-08-13, because the cut was `image_headline` (90) × 0.6
applied to a quote nobody may shorten (FR-304 > FR-105). The verbatim carve-out below is that fix.

Everything here was pure — no network, no filesystem, no money, no model — and the last
section is the one exception: `load_images()` is the product's ONLY frame loader (D49), and
since D64 the frames it loads may be `file://` URLs off the local disk. Those tests write
bytes into `tmp_path` and read them back. Still no network, no money and no model.
"""

from __future__ import annotations

import asyncio

import pytest

from hypesocials import vision_check
from hypesocials.config import TextBudgets
from hypesocials.models import CopySet, VisionCheckResult

#: The audited run's real source panel — 131 characters, which is over `image_headline` (90) and
#: comfortably under the `slide` budget (300) that actually governs a deck slide.
PANEL = ("Claude reads your whole vault every single time and Obsidian's index does not — "
         "that one swap is where the 71.5x saving comes from.")


def budgets() -> TextBudgets:
    return TextBudgets()


# --------------------------------------------------------------- what the expected text is built of


def test_expected_text_is_the_block_the_render_was_ordered_to_draw() -> None:
    """One implementation of "what did we order", mirroring `prompts_engine._onimage_text`."""
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards", subline="here is why",
                   overlay_text="Stop doing this", slide_texts=["one"])

    assert vision_check.expected_text(copy, "image") == "Wired backwards\nhere is why"
    assert vision_check.expected_text(copy, "reel") == "Stop doing this"
    assert vision_check.expected_text(copy, "carousel", slide_text=PANEL) == PANEL
    # FR-304: a deck's rendered words are its slide text alone — `carousel.py` blanks the headline
    # for a wordless panel, so no headline fallback may leak in here either.
    assert vision_check.expected_text(copy, "carousel", slide_text="") == ""
    # B1/M12: the wordmark renders THROUGH the text block, so it is part of the referent.
    assert vision_check.expected_text(copy, "carousel", slide_text=PANEL,
                                      wordmark="HypeLead") == f"{PANEL}\nHypeLead"


# ------------------------------------------------------------------ FR-304's verbatim carve-out


def test_a_mapped_panels_text_survives_the_retry_byte_for_byte() -> None:
    """GAP 2: the 131-character panel stays 131 characters (FR-304 > FR-105).

    Trimming a verbatim quote to 60% of a budget produces the mid-sentence stub this module exists
    to CATCH — committed on purpose, by us, on the one asset whose words are not ours to edit.
    """
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards", subline="here is why")

    plan = vision_check.retry_plan(copy, "carousel", budgets(), slide_text=PANEL, verbatim=True)

    assert len(PANEL) == 131, "the audited panel's real length — the fixture, not an assumption"
    assert plan.slide_text == PANEL and len(plan.slide_text) == 131
    assert plan.budget_scale == 1.0, "nothing was cut, so no smaller budget may be restated"
    assert plan.instruction == vision_check.VERBATIM_RETRY_INSTRUCTION
    assert "LOCKED" in plan.instruction and "layout" in plan.instruction, \
        "the difference this retry makes is layout-side (fewer elements, larger type)"


def test_a_free_composed_deck_slide_is_cut_against_the_slide_budget_not_the_headline() -> None:
    """The −40% survives for text WE wrote — measured against the slot that governs a deck slide.

    `image_headline` (90) is four times smaller than `slide` (300) and governs a cover headline,
    not a page: cutting a 131-character deck line against it was how a whole thought became a stub.
    """
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards")

    plan = vision_check.retry_plan(copy, "carousel", budgets(), slide_text=PANEL)

    assert plan.slide_text == PANEL, "131 chars is inside slide(300)×0.6 = 180 — nothing to cut"
    assert plan.budget_scale == pytest.approx(0.6)
    long_line = " ".join(["word"] * 60)  # 299 characters: over 180, under the 300 ceiling
    cut = vision_check.retry_plan(copy, "carousel", budgets(), slide_text=long_line).slide_text
    assert 0 < len(cut) <= 180 and not long_line.startswith(cut + "x"), "cut at a word boundary"
    assert cut and long_line.startswith(cut)


def test_a_free_text_image_retry_still_cuts_forty_percent_of_its_own_budget() -> None:
    """The rule that did NOT change: an image's headline is ours, so it is still shortened.

    `image_headline` is the slot that governs a standalone image, the subline is dropped as the
    optional block, and the stated budget travels with the text via `budget_scale`.
    """
    headline = " ".join(["headline"] * 20)  # 179 characters, well over image_headline(90)
    copy = CopySet(asset_id="a", language="en", headline=headline, subline="a second block")

    plan = vision_check.retry_plan(copy, "image", budgets())

    assert len(plan.copy.headline) <= 54, "90 × 0.6, cut at a word boundary"
    assert headline.startswith(plan.copy.headline), "a prefix, never a re-write"
    assert plan.copy.subline == "", "fewer blocks render more reliably than shorter ones"
    assert plan.budget_scale == pytest.approx(0.6)
    assert plan.instruction == vision_check.RETRY_INSTRUCTION


def test_a_reel_retry_is_unchanged_and_cuts_against_the_seed_headline_budget() -> None:
    """A seed frame's hook is free-composed too, and its own slot is `reel_seed_headline`(60)."""
    hook = " ".join(["hook"] * 30)  # 149 characters
    copy = CopySet(asset_id="a", language="en", overlay_text=hook, headline=hook, subline="drop")

    plan = vision_check.retry_plan(copy, "reel", budgets())

    assert len(plan.copy.overlay_text) <= 36 and hook.startswith(plan.copy.overlay_text)
    assert plan.copy.subline == "" and plan.budget_scale == pytest.approx(0.6)


# ------------------------------------------------------------- D-D: the counter is ordered text


def test_the_expected_text_lists_the_slide_counter_as_ordered_words() -> None:
    """A counted deck orders its badge as a locked TEXT string, so it is part of the referent.

    Unlisted, "3/7" reads to the checker as three invented characters on every slide of the deck —
    a `text_mismatch` on the whole deck, earning a retry per slide against a defect nobody has.
    """
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards", subline="here is why")

    assert vision_check.expected_text(copy, "carousel", slide_text=PANEL,
                                      slide_counter="03 / 05") == f"{PANEL}\n03 / 05"
    # The order mirrors the TEXT block the render was given: words, counter, signature.
    assert vision_check.expected_text(copy, "carousel", slide_text="Slide one",
                                      slide_counter="1/5", wordmark="HypeLead") == (
        "Slide one\n1/5\nHypeLead")
    assert vision_check.expected_text(copy, "carousel", slide_text=PANEL) == PANEL, \
        "an uncounted deck lists no badge — the opposite claim, just as sharp"
    # A wordless mapped panel of a COUNTED deck is not wordless: the badge is still ordered.
    assert vision_check.expected_text(copy, "carousel", slide_text="",
                                      slide_counter="02 / 05") == "02 / 05"


# --------------------------------------------------------- D-F: the retry knows which defect


def test_a_mismatch_retry_names_the_invented_words_and_forbids_them() -> None:
    """D-F: "shorter text, larger type" is a remedy for broken glyphs and a no-op for invented copy.

    The first verdict's own `detail` is quoted into the instruction, so the second attempt is a
    different REQUEST rather than a second roll of the same dice.
    """
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards")
    verdict = vision_check.ImageVerdict(index=1, text_mismatch=True,
                                        detail="shows 'BUILD IN PUBLIC', not the panel's words")

    plan = vision_check.retry_plan(copy, "carousel", budgets(), slide_text=PANEL, verbatim=True,
                                   verdict=verdict)

    assert "shows 'BUILD IN PUBLIC', not the panel's words" in plan.instruction
    assert "invented or altered words" in plan.instruction
    assert "Render the invented words nowhere" in plan.instruction
    assert plan.instruction.startswith(vision_check.VERBATIM_RETRY_INSTRUCTION), \
        "the defect clause is APPENDED to the lever the caller chose, never a replacement"
    assert plan.slide_text == PANEL, "FR-304 > FR-105 still: a quote is not trimmed by a diagnosis"


def test_a_fake_ui_retry_forbids_the_chrome_the_render_actually_drew() -> None:
    """The second clause, and the second no-op: a smaller headline does not remove a play button."""
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards")
    verdict = vision_check.ImageVerdict(index=1, fake_ui=True, detail="a TikTok-style like counter")

    plan = vision_check.retry_plan(copy, "image", budgets(), verdict=verdict)

    assert "a TikTok-style like counter" in plan.instruction
    assert "platform interface chrome" in plan.instruction
    assert plan.instruction.startswith(vision_check.RETRY_INSTRUCTION)
    assert plan.copy.subline == "" and plan.budget_scale == pytest.approx(0.6), \
        "the text lever is unchanged — the clause is added ON TOP of it"


def test_a_broken_text_verdict_keeps_the_instruction_it_always_had() -> None:
    """`text_broken`'s remedy IS the base wording, and duplicating it dilutes the real clauses."""
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards")
    broken = vision_check.ImageVerdict(index=1, text_broken=True, detail="garbled diacritics")

    assert vision_check.retry_plan(copy, "image", budgets(),
                                   verdict=broken).instruction == vision_check.RETRY_INSTRUCTION
    assert vision_check.retry_plan(copy, "carousel", budgets(), slide_text=PANEL, verbatim=True,
                                   verdict=broken).instruction == (
        vision_check.VERBATIM_RETRY_INSTRUCTION)
    # No verdict in scope is the pre-D-F string, byte for byte — every caller keeps its default.
    assert vision_check.retry_plan(copy, "image",
                                   budgets()).instruction == vision_check.RETRY_INSTRUCTION
    assert vision_check.retry_plan(copy, "reel",
                                   budgets()).instruction == vision_check.RETRY_INSTRUCTION


def test_a_detail_less_verdict_still_names_the_defect() -> None:
    """A flag with no explanation still gets its defect forbidden — and no dangling dash."""
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards")

    plan = vision_check.retry_plan(copy, "reel", budgets(),
                                   verdict=vision_check.ImageVerdict(index=1, text_mismatch=True))

    assert "no further detail was given" in plan.instruction
    assert " — ." not in plan.instruction


# --------------------------------------------------------------- the one frame loader (D49/D64)
#
# `load_images()` is what every gauntlet critic call and every cover pick loads its frames with.
# Under `render_provider: codex` a result URL is a `file://` URI into `<run>/.renders/`, and SESSION
# O added `_file_url_path` for it without a test — so nothing pinned the two things that actually
# break: a run folder with a SPACE in its path (`C:/Users/Pavli/My Runs/`) arrives percent-escaped,
# and a dropped frame must not shift the frames around it (a critic reads by ATTACHMENT slot).


def test_a_file_url_loads_including_the_spaces_and_escapes_a_windows_path_carries(
    tmp_path,
) -> None:
    """`Path("file:///C:/...")` is not a path, and `%20` is not a space until it is unescaped.

    Both would have surfaced as "frame not loaded" on every deck of a codex run — a silently
    unjudged gauntlet, which is the failure mode D64's own review round already found once.
    """
    folder = tmp_path / "My Runs" / "renders"
    folder.mkdir(parents=True)
    frame = folder / "codex-abc.png"
    frame.write_bytes(b"\x89PNG frame one")
    url = frame.as_uri()
    assert "%20" in url, "the fixture only proves anything if the path really is escaped"

    assert vision_check._file_url_path(url) == frame
    blobs, positions = asyncio.run(vision_check.load_images([url]))

    assert blobs == [b"\x89PNG frame one"] and positions == [1]


def test_the_loader_still_takes_plain_paths_and_bytes_and_keeps_every_position(tmp_path) -> None:
    """Three input kinds in one call, and the 1-based slot each one came from.

    `positions` is the mapping a caller needs to turn a model's attachment slot back into its own
    slide numbering, so a frame that cannot be read has to leave a GAP in the numbers rather than
    pulling its neighbours down one.
    """
    first = tmp_path / "slide_01.png"
    first.write_bytes(b"one")
    third = tmp_path / "slide_03.png"
    third.write_bytes(b"three")
    missing = (tmp_path / "gone.png").as_uri()

    blobs, positions = asyncio.run(vision_check.load_images(
        [first, b"two", missing, str(third), third.as_uri()]))

    assert blobs == [b"one", b"two", b"three", b"three"]
    assert positions == [1, 2, 4, 5], "the unreadable third input leaves a gap, not a shift"


def test_only_a_file_scheme_is_treated_as_a_local_url() -> None:
    """`_file_url_path` answers `None` for everything `load_images` must handle another way —
    raw bytes, a plain path and an http(s) URL, which is fetched rather than opened."""
    assert vision_check._file_url_path(b"bytes") is None
    assert vision_check._file_url_path("C:/runs/slide_01.png") is None
    assert vision_check._file_url_path("https://cdn.kie.ai/x/y.jpg") is None
