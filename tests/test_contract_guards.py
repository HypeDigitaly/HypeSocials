"""D65/FR-362/FR-363 — the panel-map contract guards, on the audit's own defects.

`panel_map.source_text` is not provenance. It is the ORDER: the render prompt quotes it, the
post-render critics demand it back off the frame, and `cover_pick` chooses a cover by how well the
frame carries it. So every fixture in this file is a real corrupted order from the 2026-08-21
audit, and every assertion is about what the renderer would have been told to draw:

* `I6GB`, `I46K STARS`, `IOX`, `7OB` drawn as pixels with the right digits sitting on the same
  row's `source_text_original`, and `28GB` where the source said `128GB`;
* run 4344's `Ig_08`, whose rows carried the PREVIOUS row's text while their own sat one up;
* `Documents / Documents` demanded twice, and critics failing the frame for printing it once;
* `Gbillington1 merged commit 859bdce into dev`, `Clearform-Labs/tldr #125` and an incidental tote
  bag's `OPAL COLLECTION` locked in as REQUIRED verbatim text;
* `EVOLVING AI` — the creator's own watermark — promoted to a hero headline;
* a body panel ending `( src/types/in`, and a slide reading `ran the cheap experiment you asked
  for.` after its subject (the creator's handle) was correctly removed from the line above;
* source panels with neither a row nor a drop reason: a deck of 12 shipped as a success of 10.

Two levels, deliberately weighted towards the first:

1. **The pure guards** (`hypesocials.contract_guard`) — strings and dicts in, strings and dicts
   out, no I/O, no config. Nine rules, their negative cases and the ladder's ORDER, tested
   directly, because that is where a rule can be stated once and pinned exactly.
2. **The one seam** (`copywrite._guarded`) — a much smaller set, asserting only that the guards
   are REACHED on all four copy walks (verbatim, compressed, auto, translated), on both degrade
   tiers, and that the caption half still runs when the deck half is skipped. Nothing here
   re-tests a rule that section 1 already pins.

Every anti-regression case in this file is load-bearing. A guard that fires on a legitimately
compressed row un-compresses decks the operator asked to be compressed; one that fires on a source
deck longer than the platform ceiling prints a scary warning about a decision the plan made on
purpose; one that strips the tool a SaaS-tour deck is ABOUT costs that slide its subject. Those
cases sit beside the defect they mirror, never in a section of their own.

No network, no LLM, no renders: section 1 calls pure functions and section 2 rides the same
`StructuredCall` stubs `tests/test_copywrite.py` already owns.
"""

from __future__ import annotations

from typing import Any

import pytest

from hypesocials import contract_guard as cg
from hypesocials import copywrite
from hypesocials.config import TextBudgets
from hypesocials.models import Brief, CopySet, DegradationTag, PlanEntry, SourcePost
from hypesocials.prompts_engine import PromptEngine
from hypesocials.topic_filter import collapse
from tests.test_copywrite import (
    Recorder,
    SchemaCall,
    StubCall,
    compress_deck,
    compressed,
    context,
    deck_entry,
    deck_style,
    entry,
    foreign_deck,
    free_text,
    german_trend,
    make_style,
    make_trend,
    post,
    selection,
    translated,
)

#: The audit's own defect strings, named once so a fixture cannot drift from the run it came from.
COMMIT_LINE = "Gbillington1 merged commit 859bdce into dev"
REPO_REF = "Clearform-Labs/tldr #125"
ORPHAN = "ran the cheap experiment you asked for."
WATERMARK = "EVOLVING AI"
TOTE_BAG = "OPAL COLLECTION"
CUT_TAIL = "The types all live in ( src/types/in"
WHOLE_TAIL = "The types all live in (src/types/index.ts) and nowhere else"


# --------------------------------------------------------------------------------- builders


def row(slide: int, shipped: str, original: str | None = None, **overrides: Any) -> dict[str, Any]:
    """One `panel_map` row in the shape all four copy walks produce (D54's one-row schema).

    `original` defaults to `shipped`, which is what a clean VERBATIM row looks like — the walk that
    carries most decks — so a fixture only has to state the two strings when they disagree, and
    the disagreement is the defect under test.
    """
    data: dict[str, Any] = {
        "slide": slide, "source_position": slide, "source_text": shipped,
        "source_text_original": shipped if original is None else original,
        "ref_label": f"P1.panel.{slide}", "drop_reason": "", "creator_stripped": False,
        "chrome_counter_stripped": False, "truncation_suspect": False, "compressed": False,
        "translated": False}
    data.update(overrides)
    return data


def guard(rows: list[dict[str, Any]], *, admits: Any = None, **kwargs: Any) -> cg.GuardedDeck:
    """`guard_deck` with the scaffolding every call shares — `admits` says yes by default.

    The copy stage passes its own `_panel_verdict` gate here, so the default is the honest one for
    a unit test: these panels were admitted by the walk, and the tests that care about a REFUSED
    fallback pass their own predicate.
    """
    return cg.guard_deck(rows, asset_id="Ig_08", admits=admits or (lambda text: True), **kwargs)


def texts(guarded: cg.GuardedDeck) -> list[str]:
    return list(guarded.texts)


def tags(guarded: cg.GuardedDeck | Any) -> list[str]:
    return [tag.value for tag in guarded.tags]


def events(guarded: cg.GuardedDeck | cg.GuardedCaption) -> list[str]:
    return [warning.event_type for warning in guarded.warnings]


def message(guarded: cg.GuardedDeck | cg.GuardedCaption, event_type: str) -> str:
    return next(w.message for w in guarded.warnings if w.event_type == event_type)


# ============================================================ guard 1 — digits (FR-362.1)


@pytest.mark.parametrize("shipped,original,healed", [
    ("I6GB of unified memory", "16GB of unified memory", "16GB"),
    ("I46K STARS on GitHub", "146K STARS on GitHub", "146K"),
    ("IOX faster than the old one", "10X faster than the old one", "10X"),
    ("A 7OB model on one card", "A 70B model on one card", "70B"),
])
def test_fr362_the_audits_own_ocr_misreadings_are_healed_from_the_rows_own_original(
    shipped: str, original: str, healed: str
) -> None:
    """The four tokens run 4344 rendered as pixels, each healed against its OWN source panel.

    `I`, `l`, `O` and `o` were standing where the source has DIGITS, so the corrected bytes are the
    source's own and nothing was invented. It is a repair rather than a loss — `ocr_repair`'s
    doctrine already sanctions exactly this substitution at admission — and the finding says so by
    landing in `repaired` rather than in `restored`.
    """
    finding = cg.guard_digits(shipped, original)

    assert finding.text == original, "the healed row is the source panel, character for character"
    assert len(finding.repaired) == 1, "one token was misread, so one token was healed"
    assert finding.repaired[0][1] == healed, "and the healed bytes are the original's own"
    assert not finding.restored and not finding.row_replaced
    assert not finding.drifted, "a repair is not a drift and must never earn the tag"


def test_fr362_a_healed_deck_reports_the_repair_and_earns_no_degradation_tag() -> None:
    """Guard 1 at deck level: the console line names the slide and both tokens, and the creative
    is NOT tagged. `copy_digit_drift` means "the row claimed a number the source did not"; an OCR
    letter standing in for a digit is the opposite of that — it is the row being put back."""
    guarded = guard([row(1, "I6GB of RAM, IOX the throughput", "16GB of RAM, 10X the throughput")])

    assert texts(guarded) == ["16GB of RAM, 10X the throughput"]
    assert tags(guarded) == [], "a repair is free of tags by design"
    assert events(guarded) == ["panel_digits_repaired"]
    assert "slide 1 (I6GB -> 16GB)" in message(guarded, "panel_digits_repaired")
    assert "slide 1 (IOX -> 10X)" in message(guarded, "panel_digits_repaired")


def test_fr362_a_dropped_leading_digit_restores_the_sources_token_and_tags_the_drift() -> None:
    """`28GB` where the source panel says `128GB` — the dropped-leading-digit class.

    There is no honest repair here: the two tokens are not the same length, so `repair_token`
    refuses and `token_drifted` recognises the counterpart instead. The SOURCE's bytes ship in that
    token's place and the creative is tagged, because a number on a slide is a claim about the
    world and a claim the source never made is what the verbatim contract exists to prevent.
    """
    guarded = guard([row(1, "28GB unified memory, 8 cores", "128GB unified memory, 8 cores")])

    assert texts(guarded) == ["128GB unified memory, 8 cores"], "surgery on the token alone"
    assert tags(guarded) == ["copy_digit_drift"]
    assert "slide 1 (28GB -> 128GB)" in message(guarded, "copy_digit_drift")


def test_fr362_a_number_the_source_never_wrote_replaces_the_whole_row() -> None:
    """The pm3y fabrication class: `1.5%` against a source panel that says `13.8%`.

    These two are not a misreading of one another — no confusable stands anywhere, and neither
    digit string is a prefix, a suffix or a one-place variant of the other — so there is no token
    to operate on. The token structure differs too far for surgery, `row_replaced` says so, and the
    WHOLE source panel ships instead. A legitimately different number is never silently "repaired"
    into the source's; it is refused, and the refusal is loud.
    """
    guarded = guard([row(1, "Latency fell 1.5% this quarter",
                         "Latency fell 13.8% this quarter")])

    assert texts(guarded) == ["Latency fell 13.8% this quarter"]
    assert tags(guarded) == ["copy_digit_drift"]
    assert "numbers the source panel never wrote" in message(guarded, "copy_digit_drift")


def test_repair_token_refuses_everything_that_is_not_one_misreading_of_one_token() -> None:
    """The repair is total and unforgiving, which is what makes it safe to run over every row.

    Same length, every character either equal or a sanctioned confusable standing where the
    original has a DIGIT. One character out of place and this answers `None`, which hands the pair
    to the drift test rather than quietly rewriting it.
    """
    assert cg.repair_token("I6GB", "16GB") == "16GB"
    assert cg.repair_token("7OB", "70B") == "70B"
    assert cg.repair_token("28GB", "128GB") is None, "a length difference is not a misreading"
    assert cg.repair_token("I6GB", "16MB") is None, "the unit differs — a different measurement"
    assert cg.repair_token("16GB", "16GB") is None, "nothing to repair"
    assert cg.repair_token("16GB", "I6GB") is None, "one-directional: a digit never becomes letter"
    assert cg.repair_token("I", "1") is None, "a one-character token is never repaired"


def test_a_lone_pronoun_is_never_read_as_arithmetic() -> None:
    """The English `I` and a source panel's lone `1` are the same shape, and healing one into the
    other would rewrite prose into a number. `_MIN_REPAIRABLE` is what forbids it, and a sentence
    that opens on the pronoun comes back byte for byte."""
    finding = cg.guard_digits("I tested 11 tools this month", "I tested 11 tools this month")

    assert finding.text == "I tested 11 tools this month"
    assert not finding.repaired and not finding.restored and not finding.row_replaced


def test_token_drifted_reads_a_misreading_and_never_two_different_numbers() -> None:
    """The predicate's whole judgement in one place: a counterpart, not a coincidence."""
    assert cg.token_drifted("28GB", "128GB"), "the dropped leading digit"
    assert cg.token_drifted("746K", "146K"), "same length, one place apart"
    assert not cg.token_drifted("1.5%", "13.8%"), "simply different numbers"
    assert not cg.token_drifted("16GB", "16MB"), "different units are different measurements"
    assert not cg.token_drifted("16GB", "16GB"), "identical is not drift"
    assert not cg.token_drifted("tools", "16GB"), "a token with no digits is never judged"


def test_digits_of_ignores_the_separator_so_a_comma_and_a_point_are_one_measurement() -> None:
    """A German panel writes `1,5 %` and its English translation writes `1.5%`; those are the same
    measurement, and the drift test must not report the separator as a changed digit."""
    assert cg.digits_of("1,5 %") == cg.digits_of("1.5%") == "15"
    assert not cg.token_drifted("1.5%", "1,5 %"), "the same number, punctuated two ways"


def test_a_translated_row_keeps_its_words_when_only_the_decimal_separator_moved() -> None:
    guarded = guard([row(1, "Latency dropped 1.5% last quarter",
                         "Latenz sank um 1,5 % im letzten Quartal", translated=True)])

    assert texts(guarded) == ["Latency dropped 1.5% last quarter"]
    assert tags(guarded) == []


async def test_a_panel_the_admission_repair_corrupted_ships_its_own_digits_again() -> None:
    """The measurement round trip, end to end and with no model in the loop.

    `I6GB` and `IOX` never arrived from a vision pass on this deck: Virlo's panels say `16GB` and
    `10X`, and `copywrite._repaired` MANUFACTURED the letters itself at admission — the root
    cause D65 found underneath guard 1's whole fixture list. Two independent things now keep this
    deck honest, and the test asserts the outcome rather than which of them did the work:
    `ocr_repair` no longer reads a measurement as an acronym (the test below pins that directly),
    and guard 1 still diffs `source_text` against `source_text_original` for every corruption that
    arrives from somewhere this engine does not control. Both slides render the source's own
    numbers and the creative is not tagged, because nothing drifted.
    """
    log = Recorder()
    trend = make_trend(post(1, panels=("The machine ships with 16GB of memory.",
                                       "10X faster than the old one"),
                            caption="A caption long enough to be a caption at all."))
    call = StubCall({"d1": selection(caption_ref="P1.caption")})

    result = await copywrite.write_copy([deck_entry(slides=2)], call=call, log=log, **context(
        trends={"t1": trend}, styles={"flat-card": deck_style()}))

    assert result.copy["d1"].slide_texts == ["The machine ships with 16GB of memory.",
                                             "10X faster than the old one"]
    assert result.tags.get("d1", ()) == (), "a repair is not a degradation"
    assert not log.warned("panel_digits_drifted"), "and nothing drifted"


def test_a_measurement_token_is_not_an_acronym_and_keeps_its_digits_at_admission() -> None:
    from hypesocials.ocr_repair import repair_confusables

    assert repair_confusables("16GB of unified memory")[0] == "16GB of unified memory"
    assert repair_confusables("146K STARS on GitHub")[0] == "146K STARS on GitHub"
    assert repair_confusables("10X faster than the old one")[0] == "10X faster than the old one"
    assert repair_confusables("A 70B model on one card")[0] == "A 70B model on one card"


# ==================================================== guard 2 — row alignment (FR-362.2)


#: Run 4344's `Ig_08`, in miniature: slide 3 carries slide 2's text while its own sits one row up.
IG_08 = [
    row(1, "Repo one ships a terminal dashboard for docker containers"),
    row(2, "Repo two turns markdown notes into a searchable wiki site"),
    row(3, "Repo two turns markdown notes into a searchable wiki site",
        "Repo three renders architecture diagrams straight from code"),
]


def test_fr362_the_ig_08_shape_puts_each_row_back_on_its_own_source_panel() -> None:
    """The misalignment defect end to end: nothing is RE-ORDERED, the row is re-worded.

    FR-304's alignment is never broken to fix a row — the row stays, the position stays, only the
    words change — so slide 3 ships source panel 3's verbatim bytes and slides 1–2 are untouched.
    The warning names both overlaps, because "0.12 with its own panel, 1.00 with source panel 2"
    is the evidence, and an operator reading a realignment deserves to see it.
    """
    guarded = guard(IG_08)

    assert texts(guarded) == [
        "Repo one ships a terminal dashboard for docker containers",
        "Repo two turns markdown notes into a searchable wiki site",
        "Repo three renders architecture diagrams straight from code"]
    assert tags(guarded) == ["panel_map_realigned"]
    assert "with source panel 2" in message(guarded, "panel_map_realigned")
    assert [r["source_position"] for r in guarded.rows] == [1, 2, 3], "positions never move"


def test_fr362_a_legitimately_compressed_row_is_never_realigned() -> None:
    """The anti-regression that decides whether this guard is usable at all.

    A compressed row is a humanised summary of an 800-character panel: it may share very little
    vocabulary with its own original and still be a perfectly honest rendering of it. Firing on
    that alone would un-compress every deck the operator asked to be compressed. What is NOT
    ambiguous is a row whose words match a DIFFERENT row's panel better than their own — so the
    guard needs both halves, and neither of these rows has the second one.
    """
    rows = [
        row(1, "Containers, visible at last",
            "The first repository ships a terminal dashboard that lets you watch every docker "
            "container, its memory and its logs, without ever leaving the shell", compressed=True),
        row(2, "Notes become a wiki",
            "The second repository turns a folder of markdown notes into a searchable, linkable "
            "wiki site that rebuilds itself on every save", compressed=True),
    ]

    guarded = guard(rows)

    assert texts(guarded) == ["Containers, visible at last", "Notes become a wiki"]
    assert tags(guarded) == [] and events(guarded) == []
    assert cg.content_overlap(rows[0]["source_text"], rows[0]["source_text_original"]) == 0.0, \
        "a poor fit at home is a suspicion; only a better home elsewhere is a finding"


def test_content_overlap_is_containment_so_a_faithful_compression_scores_high() -> None:
    """Containment, never Jaccard, and the difference is the whole guard.

    Every word a compression KEPT came from the panel, so containment reads ≈ 1.0 while Jaccard —
    dragged down by the 700 characters the compression dropped — reads under any floor worth
    having. Containment still reads 0.0 for the defect this guard exists to catch.
    """
    panel = ("The first repository ships a terminal dashboard for docker containers and their "
             "logs, memory and restart history, without ever leaving the shell")

    assert cg.content_overlap("Terminal dashboard for docker containers", panel) == 1.0
    assert cg.content_overlap("Nothing whatsoever alike", panel) == 0.0
    assert cg.content_overlap("", panel) == 1.0, "nothing to judge is not misaligned"


def test_best_rival_ignores_rows_too_short_to_be_evidence() -> None:
    """Two four-word lines from one deck share a word by accident all the time, so a containment
    ratio over very short text is noise. Guard 2 does not look at those rows — and they are also
    the rows a misalignment is least able to damage."""
    originals = ["Repo two turns markdown notes into a searchable wiki site",
                 "Repo three renders architecture diagrams straight from code"]

    assert cg.best_rival("Ship it", originals, 1) == (0, 0.0), "too few content words to judge"
    assert cg.best_rival("Repo two turns markdown notes into a searchable wiki site",
                         originals, 1) == (1, 1.0)


def test_fr362_a_second_row_claiming_one_source_panel_is_realigned_and_the_first_claim_wins() -> None:
    """Two rows pointing at one source panel is FR-304's alignment broken at the root — the deck
    is telling the gallery that two of our slides render the same slide of theirs. The FIRST claim
    is the one the walk built in order, so it stands; the later one is put back on its own panel."""
    rows = [row(1, "Panel one, as its author wrote it"),
            row(2, "Panel one, as its author wrote it", "Panel two, as its author wrote it",
                source_position=1)]

    assert cg.duplicate_positions(rows) == [1], "the SECOND row is the duplicate claim"
    guarded = guard(rows)

    assert texts(guarded) == ["Panel one, as its author wrote it",
                              "Panel two, as its author wrote it"]
    assert tags(guarded) == ["panel_map_realigned"]
    assert "a second row claiming source panel 1" in message(guarded, "panel_map_realigned")


def test_a_translated_row_is_never_realigned_for_being_in_another_language() -> None:
    """A translated row shares no content words with its own original BY DESIGN, and its rival is
    whichever row happens to be written in the language it was translated into. Realigning it
    would put the deck back into the language the operator asked us to translate out of — so
    guard 2 skips those rows entirely, and only guard 1's token surgery still applies."""
    rows = [row(1, "We tested eleven tools and only three survived the working week"),
            row(2, "We tested eleven tools and only three survived the working week",
                "Wir haben elf Werkzeuge getestet und nur drei haben die Woche ueberlebt",
                translated=True)]

    guarded = guard(rows)

    assert texts(guarded)[1] == "We tested eleven tools and only three survived the working week"
    assert tags(guarded) == [] and events(guarded) == []


# ======================================================= guard 3 — duplicate lines (FR-362.3)


def test_fr362_a_repeated_line_collapses_and_the_first_occurrence_keeps_its_bytes() -> None:
    """`Audio / Documents / Documents / AI` — what a vision pass produces when a source slide's
    list renders one row twice. Shipped into the contract it is an ORDER to print the duplicate,
    and the post-render critics then fail the frame for obeying it only once."""
    collapsed, dropped = cg.dedupe_lines("Audio\nDocuments\nDocuments\nAI")

    assert collapsed == "Audio\nDocuments\nAI"
    assert dropped == ["Documents"]


def test_dedupe_never_merges_two_lines_that_merely_start_alike() -> None:
    """Exact equality after `strip()`, casefolded, and nothing looser: two lines that begin the
    same way are two lines. Blank lines are spacing rather than content and are never deduped —
    a panel's shape is part of what it says."""
    assert cg.dedupe_lines("Documents\nDocument") == ("Documents\nDocument", [])
    assert cg.dedupe_lines("Audio\n\nDocuments\n\nAI")[1] == []
    assert cg.dedupe_lines("Documents\n  documents  ") == ("Documents", ["documents"]), \
        "case and surrounding space are not a difference"
    assert cg.dedupe_lines("One single line") == ("One single line", [])


def test_fr362_the_deck_level_dedupe_names_the_slide_and_the_line_it_collapsed() -> None:
    guarded = guard([row(1, "Audio\nDocuments\nDocuments\nAI")])

    assert texts(guarded) == ["Audio\nDocuments\nAI"]
    assert events(guarded) == ["panel_lines_deduped"]
    assert "slide 1 (1 repeated line(s): Documents)" in message(guarded, "panel_lines_deduped")
    assert guarded.rows[0]["source_text_original"] == "Audio\nDocuments\nDocuments\nAI", \
        "the evidence is never rewritten — only what ships changes"


# ============================================ guards 4 and 9 — identity and chrome (FR-362.4/.7)


def test_fr362_a_commit_line_is_removed_whole_and_the_row_says_so() -> None:
    """`Gbillington1 merged commit 859bdce into dev` names a person, a repository and a hash, none
    of which is our creative's content — and the renderer was DRAWING it, in our brand colour,
    because the contract said to. The line goes whole rather than edited: a sentence with the name
    cut out of its middle is a sentence nobody wrote and nobody proof-read."""
    guarded = guard([row(1, f"{COMMIT_LINE}\nThe agent now writes its own tests")])

    assert texts(guarded) == ["The agent now writes its own tests"]
    assert guarded.rows[0]["identity_scrubbed"] is True
    assert guarded.rows[0]["chrome_watermark_stripped"] is False
    assert guarded.rows[0]["source_text_original"].startswith(COMMIT_LINE), "the evidence stays"
    assert f"slide 1 ({COMMIT_LINE})" in message(guarded, "panel_identity_scrubbed")


def test_fr362_a_bare_repository_reference_goes_and_a_technical_url_in_a_sentence_stays() -> None:
    """`Clearform-Labs/tldr #125` on a line of its own is somebody's issue tracker. The same
    string inside a sentence is the CONTENT of a developer slide (FR-319's technical carve-out),
    and a guard that shredded it would be reversing a decision this engine already made."""
    guarded = guard([row(1, f"{REPO_REF}\nThe parser was rewritten in an afternoon"),
                     row(2, "Clone it from github.com/user/repo and run make install"),
                     row(3, "#125\nShipped on a Friday")])

    assert texts(guarded) == ["The parser was rewritten in an afternoon",
                              "Clone it from github.com/user/repo and run make install",
                              "Shipped on a Friday"]
    assert [r["identity_scrubbed"] for r in guarded.rows] == [True, False, True]


def test_fr362_an_incidental_wordmark_row_is_stripped_into_chrome_under_its_own_flag() -> None:
    """`OPAL COLLECTION` off a tote bag in the source photo, locked in as REQUIRED verbatim text.

    It is chrome exactly like the page counter `_strip_counter_lines` removes, and it rides its own
    flag for the same reason: a watermark is nobody's brand of ours and must not tag the creative
    `competitor_stripped`.
    """
    marks = cg.mark_identifiers(["Opal Collection logo"])

    guarded = guard([row(1, TOTE_BAG), row(2, "The bag was not the point of the slide")],
                    marks=marks)

    assert texts(guarded) == ["", "The bag was not the point of the slide"]
    assert [r["chrome_watermark_stripped"] for r in guarded.rows] == [True, False]
    assert [r["identity_scrubbed"] for r in guarded.rows] == [False, False], "not an identity"
    assert guarded.rows[0]["source_text_original"] == TOTE_BAG, "kept, exactly like a counter"
    assert f"slide 1 ({TOTE_BAG})" in message(guarded, "panel_watermark_stripped")
    assert guarded.dropped_refs == ("slide_1",), "a wordless row claims no label"


def test_fr362_a_mark_the_deck_is_about_survives_on_its_own_slide() -> None:
    """The discriminator, and the one real risk in guard 9: `OPAL COLLECTION` off an incidental
    tote bag and `Notion` off the tool a SaaS-tour deck reviews are the same SHAPE — a row that is
    nothing but somebody's wordmark. They differ in the rest of the deck: a mark the deck is ABOUT
    is written into other panels' sentences, and stripping it would cost that slide its subject."""
    marks = cg.mark_identifiers(["Notion logo icon", "Opal Collection logo"])
    rows = [row(1, "Notion"), row(2, "Notion replaced every doc we kept in Drive"),
            row(3, TOTE_BAG)]

    assert cg.subject_marks(rows, marks) == {"notion"}
    guarded = guard(rows, marks=marks)

    assert texts(guarded) == ["Notion", "Notion replaced every doc we kept in Drive", ""]
    assert [r["chrome_watermark_stripped"] for r in guarded.rows] == [False, False, True]


def test_mark_identifiers_peels_the_vision_passs_descriptors_and_drops_the_sanctioned_ones() -> None:
    """A row reads `OPAL COLLECTION` while the vision pass wrote `Opal Collection logo`, so both
    sides are peeled and collapsed or the join silently misses. `sanctioned` is the seam for the
    render side's actually-cropped tool patches (FR-315), which are marks a slide is entitled to
    draw; anything under the creator-identifier floor is discarded as too short to mean anything."""
    assert cg.mark_identifiers(["Opal Collection logo"]) == {"opalcollectionlogo", "opalcollection"}
    # The PEELED key is the one a row can match — a slide says `NOTION`, never `Notion logo icon` —
    # and it is the one the sanction withdraws. The raw descriptor keeps its own key, which only a
    # row that reprinted the vision pass's own words could ever hit.
    assert cg.mark_identifiers(["Notion logo icon"], sanctioned=["Notion"]) == {"notionlogoicon"}
    assert "notion" not in cg.mark_identifiers(["Notion logo icon"], sanctioned=["Notion"])
    assert cg.mark_identifiers(["AI"]) == set(), "two characters match half of every deck"


def test_fr362_beheading_leaves_the_row_wordless_rather_than_shipping_the_orphan() -> None:
    """Run 1zqv shipped `ran the cheap experiment you asked for.` — a slide whose subject was the
    creator's handle on the line above, correctly removed, leaving an ORDER to render a sentence
    with no subject. A wordless slide in its own position is the honest answer; the orphan is not."""
    guarded = guard([row(1, f"Gbillington1\n{ORPHAN}")],
                    identifiers=[collapse("Gbillington1")])

    assert texts(guarded) == [""], "nothing rather than a fragment of somebody else's sentence"
    assert guarded.rows[0]["identity_scrubbed"] is True
    assert guarded.rows[0]["source_text_original"].endswith(ORPHAN), "the evidence survives"
    assert "row left wordless: what remained read as a fragment" in message(
        guarded, "panel_identity_scrubbed")
    assert guarded.dropped_refs == ("slide_1",)


def test_beheaded_is_silent_when_the_opening_line_survived() -> None:
    """A row that lost a MIDDLE or a TRAILING line is never beheaded: whatever led it still leads
    it. The test fires only on a lost FIRST line whose replacement reads as a continuation — lower
    case, or a conjunction — because source on-image text is overwhelmingly sentence-cased."""
    assert cg.beheaded("Handle\nran the experiment", "ran the experiment")
    assert cg.beheaded("Handle\nand then it shipped", "and then it shipped")
    assert not cg.beheaded("The headline\nHandle", "The headline"), "the opening line survived"
    assert not cg.beheaded("Handle\nThe agent writes tests", "The agent writes tests")
    assert not cg.beheaded("Handle", ""), "an empty row is already wordless"


def test_strip_lines_equal_is_never_a_substring_test() -> None:
    """`labs` is inside half of every English hook, so a substring rule would quietly shred the
    verbatim contract. A line is dropped iff its own COLLAPSED form equals an identifier."""
    text = "Clearform Labs\nThe labs that built it shipped on a Friday"

    kept, dropped = cg.strip_lines_equal(text, {collapse("Clearform Labs")})

    assert kept == "The labs that built it shipped on a Friday"
    assert dropped == ["Clearform Labs"]
    assert cg.strip_lines_equal(text, set()) == (text, []), "no identifiers, no change"


def test_fr362_a_watermark_carried_as_a_row_prefix_is_stripped_into_chrome() -> None:
    guarded = guard([row(1, f"{WATERMARK}\nThe 3 tools that replaced my stack"),
                     row(2, "Everything else was noise")],
                    marks=cg.mark_identifiers([WATERMARK]))

    assert texts(guarded) == ["The 3 tools that replaced my stack", "Everything else was noise"]
    assert guarded.rows[0]["chrome_watermark_stripped"] is True
    assert guarded.rows[0]["source_text_original"].startswith(WATERMARK)


def test_fr362_a_watermark_that_is_the_whole_row_is_stripped_into_chrome() -> None:
    """The half of the `EVOLVING AI` defect the shipped guard DOES catch: the creator's watermark
    standing alone as a slide's entire text, promoted to a hero headline — and then chosen as the
    cover, because `cover_pick` reads the same corrupted contract."""
    guarded = guard([row(1, WATERMARK), row(2, "The 3 tools that replaced my stack")],
                    marks=cg.mark_identifiers([WATERMARK]))

    assert texts(guarded) == ["", "The 3 tools that replaced my stack"]
    assert guarded.rows[0]["chrome_watermark_stripped"] is True
    assert "slide 1" in message(guarded, "panel_watermark_stripped")


# ========================================================== guard 5 — truncation (FR-362.5)


def test_fr362_a_row_that_stops_on_an_open_bracket_ships_its_un_truncated_original() -> None:
    """The 1zqv fixture: a body panel ending `( src/types/in`. The parenthesis opened, the path
    inside it was cut off mid-word, and `ocr_repair.truncation_suspect` cannot see it — the line is
    under its 60-character floor and `in` is under its token floor. An open bracket with no partner
    is unambiguous in a way a trailing word never is: a source author does not write half a
    parenthesis."""
    guarded = guard([row(1, CUT_TAIL, WHOLE_TAIL)])

    assert texts(guarded) == [WHOLE_TAIL]
    assert events(guarded) == ["panel_truncation_gated"]
    assert "slide 1 (ends on '(', restored)" in message(guarded, "panel_truncation_gated")
    assert guarded.dropped_refs == ("slide_1",), "the row no longer ships the label's bytes"


def test_fr362_a_row_cut_the_same_way_as_its_original_goes_wordless() -> None:
    """There is no un-truncated original to restore, so the slide renders wordless in its own
    position. The operator would rather have a wordless frame than a public one that ends on an
    open bracket."""
    guarded = guard([row(1, CUT_TAIL)])

    assert texts(guarded) == [""]
    assert "slide 1 (ends on '(', wordless)" in message(guarded, "panel_truncation_gated")


def test_fr362_an_inherited_suspect_flag_may_restore_but_never_blanks_a_good_row() -> None:
    """The deliberate narrowing, and the reason this guard did not empty half the suite's decks.

    `truncation_suspect` is inherited from admission and its strongest arm fires on any panel over
    60 characters that ends on a lower-case word with no full stop — which is how a great many
    perfectly finished carousel panels end. Given the power to blank, it would empty slides by the
    dozen. So it may RESTORE an un-cut original, and where there is no better original to ship it
    leaves the words alone, with the flag still riding to the critic that can see the frame.
    """
    intact = "The three tools that survived the test"
    kept = guard([row(1, intact, truncation_suspect=True)])
    restored = guard([row(1, "The three tools that", intact, truncation_suspect=True)])

    assert texts(kept) == [intact], "no visible cut and no better original — the row is left alone"
    assert events(kept) == [], "and it is silent about it"
    assert texts(restored) == [intact]
    assert "slide 1 (flagged at admission, restored)" in message(
        restored, "panel_truncation_gated")


def test_an_authored_ending_is_not_a_truncation() -> None:
    """The tail vocabulary is SHORT on purpose. A colon, an em dash and an ellipsis are how source
    panels legitimately end — "The 3 tools:", "all-in-one —", a cliff-hanger — and gating on them
    would blank slides that say exactly what their author meant them to say."""
    assert cg.truncated_tail("The 3 tools:") == ""
    assert cg.truncated_tail("all-in-one —") == "", "a spaced em dash is punctuation a person chose"
    assert cg.truncated_tail("and then it just stops...") == "", "an authored cliff-hanger"
    assert cg.truncated_tail("Ship it in step 3.") == "", "a finished sentence ending on a numeral"
    assert cg.truncated_tail("") == ""


def test_truncated_tail_sees_the_cut_shapes_ocr_repair_does_not() -> None:
    """The two shapes `ocr_repair.truncation_suspect` does not look at, plus the unclosed bracket
    counted over the whole row — the cut can take the closing bracket and the two lines after it.
    Only OPENS-without-closes count: a stray `)` is a typo, not a cut."""
    assert cg.truncated_tail("The types live in ( src/types/in") == "("
    assert cg.truncated_tail("Three tools,") == ","
    assert cg.truncated_tail("The steps are\n3.") == "3.", "a list marker whose item never arrived"
    assert cg.truncated_tail("It rewrote the whole develop-") == "p-", "a word cut in half"
    assert cg.truncated_tail("Read it (top to bottom)") == "", "a closed bracket is finished"
    assert cg.truncated_tail("A smiley )") == "", "a stray closer is a typo, not a cut"


def test_the_inherited_suspect_flag_is_ignored_on_a_compressed_or_translated_row() -> None:
    """The flag describes the SOURCE panel. On a compressed or a translated row the words on the
    slide are not that panel's words, so the flag is describing something that is not there — and
    only a cut this guard can SEE in the shipped bytes may gate those rows."""
    long_panel = ("The first repository ships a terminal dashboard for every docker container you "
                  "are running, with logs and memory beside each one")

    compressed_row = guard([row(1, "Containers, visible at last", long_panel,
                                compressed=True, truncation_suspect=True)])
    translated_row = guard([row(1, "Containers, visible at last", long_panel,
                                translated=True, truncation_suspect=True)])

    assert texts(compressed_row) == ["Containers, visible at last"] and events(compressed_row) == []
    assert texts(translated_row) == ["Containers, visible at last"] and events(translated_row) == []


def test_a_translated_row_goes_wordless_rather_than_back_into_its_source_language() -> None:
    """FR-343's carve-out inside FR-362: restoring `source_text_original` on a translated row would
    answer a corrupted row with a FOREIGN one — the deck would ship half in German under a receipt
    saying it is in English. That is worse than the defect being guarded, so those rows go
    wordless: a loss of one slide's words rather than a loss of the deck's language."""
    guarded = guard([row(1, "The types all live in ( src/types/in",
                         "Die Typen liegen alle in (src/types/index.ts) und nirgendwo sonst",
                         translated=True)])

    assert texts(guarded) == [""]
    assert "wordless" in message(guarded, "panel_truncation_gated")
    assert guarded.rows[0]["translated"] is False, "a row that ships nothing is no translation"


def test_a_fallback_faces_the_walks_own_admission_gate() -> None:
    """`admits` is the copy stage's own FR-304 gate, passed in rather than re-implemented here. A
    source panel the walk would have refused — a handle, a URL, a panel over the sanity ceiling —
    is not admitted by the back door either, and the slide renders wordless in its own position."""
    guarded = guard([row(1, CUT_TAIL, "Follow @growthdaily for the whole thread")],
                    admits=lambda text: "@" not in text)

    assert texts(guarded) == [""], "the original could not ship, so nothing does"


# =========================================================== guard 6 — coverage (FR-362.6)


def test_fr362_a_source_panel_with_neither_a_row_nor_a_reason_is_loud() -> None:
    """Run 4344's `Ig_02` lost source panels with no row, no drop reason and a `status: success`.

    Every row a walk builds carries a `drop_reason` (`""` when it shipped), so "has a row" and "has
    a recorded reason" are the same test — a position with a row is explained either way. A
    position with NO row is the defect. The creative still ships; what it may not do is ship
    silently.
    """
    rows = [row(1, "Panel one"), row(2, "", drop_reason="empty"),
            row(4, "Panel four", source_position=4)]

    assert cg.unmapped_positions(rows, 4) == [3]
    guarded = guard(rows, source_panel_count=4)

    assert tags(guarded) == ["panel_dropped_unmapped"]
    assert "source panel(s) [3]" in message(guarded, "panel_dropped_unmapped")
    assert "NEITHER a panel_map row NOR a recorded drop reason" in message(
        guarded, "panel_dropped_unmapped")


def test_fr362_panels_past_the_platform_ceiling_are_never_a_coverage_loss() -> None:
    """The anti-regression: a source deck LONGER than the platform's carousel maximum is truncated
    at ASSIGN, its tail panels have no row because nobody bought them, the deck is tagged
    `panels_truncated` and the operator was told at the Confirm gate. Counting those here would
    print a scary warning about a decision the plan made on purpose."""
    rows = [row(1, "Panel one"), row(2, "Panel two"), row(3, "Panel three")]

    assert cg.unmapped_positions(rows, 12) == []
    guarded = guard(rows, source_panel_count=12)

    assert tags(guarded) == [] and events(guarded) == []


def test_unmapped_positions_counts_a_recorded_drop_reason_as_explained() -> None:
    """A wordless row is not a lost panel: FR-304 already explained it, in its own position."""
    rows = [row(1, "", drop_reason="contains_handle_or_url"),
            row(2, "", drop_reason="over_sanity_ceiling"), row(3, "Panel three")]

    assert cg.unmapped_positions(rows, 3) == []
    assert cg.unmapped_positions([], 3) == [], "no rows at all is not three losses"


# ==================================================== guard 8 — caption voice (FR-363)


def test_fr363_a_first_person_caption_is_tagged_and_ships_byte_for_byte() -> None:
    """The tag IS the whole action. Run 4344 published a creator's own life story under our
    account, word for word, exactly as FR-331 says to: the words were right and the VOICE was
    wrong, and no deterministic rule can tell the operator which one they want. So the caption
    ships verbatim, the console and the gallery card carry the hand-raise, and nothing else."""
    caption = "I quit my job in March. My first client paid me in week two. It compounds."

    guarded = cg.guard_caption(caption, asset_id="d1")

    assert guarded.caption == caption, "FR-331: the engine does not rewrite a quote to sound like us"
    assert tags(guarded) == ["caption_voice_review"]
    assert "reads as the SOURCE creator's own voice" in message(guarded, "caption_voice_review")
    assert not guarded.scrubbed


def test_fr363_one_first_person_sentence_is_a_turn_of_phrase_and_stays_silent() -> None:
    """An audit that fires on every caption is an audit the operator learns to skip."""
    assert not cg.caption_voice_suspect(
        "The three tools that survived. I still use every one of them today. "
        "They cost nothing. They replaced four subscriptions. Try the first one.")
    assert cg.first_person_starts("Nothing first person here at all.") == (0, 1)


def test_fr363_a_statement_about_the_subject_is_not_the_creators_voice() -> None:
    """The test is on the OPENING of a sentence, never on the whole of it: "the tool I use every
    day" is a statement about the tool, while "I use this every day" is a statement about the
    author. Only the second can turn our account into somebody else's diary."""
    assert not cg.caption_voice_suspect("The tool I use every day is finally free.")
    assert cg.caption_voice_suspect("I use this every day. I would pay for it.")
    assert not cg.caption_voice_suspect("We tested eleven tools. Our team kept three.")


def test_fr363_an_override_briefs_caption_is_exempt_from_the_voice_test_not_from_the_scrub() -> None:
    """`quoted=False` says these words came from the OPERATOR's own directives rather than from a
    source post, so "I" in them is the operator and a tag would fire on our own house style. The
    identity scrub still runs on every caption whatever this says: a commit hash or somebody else's
    handle has no business in our caption however the caption was built."""
    caption = f"I built this in a weekend. My whole stack is three tools.\n{COMMIT_LINE}"

    brief = cg.guard_caption(caption, asset_id="d1", quoted=False)
    quoted = cg.guard_caption(caption, asset_id="d1", quoted=True)

    assert tags(brief) == [], "the operator's own voice is not a defect"
    assert COMMIT_LINE not in brief.caption and brief.scrubbed
    assert events(brief) == ["caption_identity_scrubbed"]
    assert tags(quoted) == ["caption_voice_review"], "the control: the same words off a post"


def test_fr363_a_beheaded_caption_ships_anyway_because_a_creative_needs_one() -> None:
    """The honest trade here is the OPPOSITE of the deck's: a creative with no caption cannot be
    published at all, so the fragment ships and the warning names it. On a slide the same shape
    goes wordless, because a wordless slide is still a slide."""
    guarded = cg.guard_caption(f"Gbillington1\n{ORPHAN}", asset_id="d1",
                               identifiers=[collapse("Gbillington1")])

    assert guarded.caption == f"Gbillington1\n{ORPHAN}", "the bytes survive the beheading"
    assert events(guarded) == ["caption_identity_scrubbed"]
    assert "it ships anyway" in message(guarded, "caption_identity_scrubbed")
    assert not guarded.scrubbed, "nothing was rewritten, so the verifier's pool gains nothing"


# ============================================================ the ladder: order and receipts


def test_the_restoring_guards_run_before_the_identity_scrub() -> None:
    """The ORDER is load-bearing and it is not the order the plan lists the guards in.

    Digits, alignment and truncation restore `source_text_original`, which is the source panel with
    its creator header, its watermark and its commit line still on it — layer 3 ran AFTER that
    string was recorded. Scrubbing before them would clean a string that is about to be thrown
    away and then ship the un-scrubbed one in its place. So the scrub goes last, and the invariant
    worth having holds: no byte leaves this function carrying another party's name.
    """
    guarded = guard([row(1, "The agent now writes its own tests ( src/agent/te",
                         f"{COMMIT_LINE}\nThe agent now writes its own tests "
                         "(src/agent/tests.ts)")])

    assert texts(guarded) == ["The agent now writes its own tests (src/agent/tests.ts)"]
    assert COMMIT_LINE not in texts(guarded)[0], "restored, THEN scrubbed"
    assert sorted(events(guarded)) == ["panel_identity_scrubbed", "panel_truncation_gated"]


def test_a_guard_never_rewrites_the_evidence_or_the_callers_rows() -> None:
    """`source_text_original` is the evidence and every guard writes to `source_text` alone, so the
    gallery's "what they said / what we shipped" pair stays honest. The caller's dicts are its own
    data (`CopyProvenance`), so the module returns NEW rows rather than mutating them."""
    rows = [row(1, "28GB unified memory", "128GB unified memory")]
    before = [dict(entry) for entry in rows]

    guarded = guard(rows)

    assert rows == before, "the input rows are never mutated"
    assert guarded.rows[0] is not rows[0]
    assert guarded.rows[0]["source_text_original"] == "128GB unified memory"
    assert guarded.texts == tuple(r["source_text"] for r in guarded.rows), \
        "the texts and the rows are the same strings by construction"


def test_a_row_whose_words_were_replaced_withdraws_its_label_and_its_mode_flags() -> None:
    """A restored or emptied row no longer ships the bytes its ref label claims, and it is no
    longer the compression or the translation the walk produced. The label is withdrawn (the
    caller drops it from `refs`), and the mode flags go with it — a wordless row's label is empty
    on every walk anyway, so this is FR-304's own rule applied by a later hand."""
    guarded = guard([row(1, "Latency fell 1.5% this quarter", "Latency fell 13.8% this quarter",
                         compressed=True, ref_label="P1.panel.1")])

    assert guarded.rows[0]["source_text"] == "Latency fell 13.8% this quarter"
    assert guarded.rows[0]["ref_label"] == "" and guarded.dropped_refs == ("slide_1",)
    assert guarded.rows[0]["compressed"] is False
    assert "Latency fell 13.8% this quarter" in guarded.authored, \
        "a restored original joins the verifier's pool, exactly as a compressed line does"


def test_a_healed_row_keeps_its_receipts_because_it_is_still_the_walks_own_words() -> None:
    """The other side of the line above: a healed `I6GB` or a collapsed duplicate line is still
    the compression the walk produced, and wiping those receipts would tell meta.yaml the deck
    shipped a contract it never shipped."""
    guarded = guard([row(1, "I6GB of RAM", "16GB of RAM", compressed=True)])

    assert guarded.rows[0]["source_text"] == "16GB of RAM"
    assert guarded.rows[0]["compressed"] is True, "the row is still a compression"
    assert guarded.rows[0]["ref_label"] == "P1.panel.1" and guarded.dropped_refs == ()


def test_a_clean_deck_is_silent_and_byte_identical() -> None:
    """Silence means the deck was clean, and that is the only thing silence may mean — so a guard
    that fires is visible. A wordless row has no contract to guard and is skipped entirely."""
    rows = [row(1, "Panel one, as its author wrote it"),
            row(2, "", drop_reason="empty"),
            row(3, "Panel three, as its author wrote it")]

    guarded = guard(rows, source_panel_count=3)

    assert texts(guarded) == [r["source_text"] for r in rows]
    assert not guarded.changed and guarded.authored == () and guarded.dropped_refs == ()


def test_every_row_carries_the_two_new_keys_whatever_the_guards_did() -> None:
    """D54's one-row-schema contract, extended: both D65 keys on EVERY row, false by default, so
    a reader never has to ask whether they exist."""
    guarded = guard([row(1, f"{COMMIT_LINE}\nThe agent writes its own tests"),
                     row(2, "", drop_reason="empty"), row(3, "A perfectly ordinary panel")])

    assert [r["identity_scrubbed"] for r in guarded.rows] == [True, False, False]
    assert all("chrome_watermark_stripped" in r for r in guarded.rows)


# ================================================= the seam: `copywrite._guarded` (FR-362/363)
#
# A deliberately small set. The rules are pinned above, as pure functions; what these ask is
# whether the guards are REACHED — on all four copy walks, on both degrade tiers, and on the
# caption when the deck half cannot run. One seam, checked once, after everything that writes the
# panel map has finished writing it.


def make_run(**overrides: Any) -> copywrite._Run:
    """The `_Run` scaffolding `_guarded` reads — a log, the marks table and nothing else."""
    fields: dict[str, Any] = {
        "call": None, "engine": PromptEngine(), "budgets": TextBudgets(), "styles": {},
        "conventions": {}, "onimage_languages": {}, "niche_descriptor": "", "brand_context": "",
        "competitors": (), "strip_brands": {}}
    fields.update(overrides)
    return copywrite._Run(**fields)  # type: ignore[arg-type]


def written(rows: list[dict[str, Any]], *, caption: str = "A caption, long enough to be one.",
            slides: list[str] | None = None) -> copywrite._Written:
    provenance = copywrite.CopyProvenance(post_id="p1", panel_map=rows,
                                          source_panel_count=len(rows),
                                          refs={f"slide_{r['slide']}": r["ref_label"]
                                                for r in rows if r.get("ref_label")})
    copyset = CopySet(asset_id="d1", language="en", trend_key="t1", caption=caption,
                      slide_texts=[r["source_text"] for r in rows] if slides is None else slides)
    return copywrite._Written(copyset=copyset, source=provenance)


def guarded_seam(subject: copywrite._Written, *, log: Recorder,
                 **run_kwargs: Any) -> list[DegradationTag]:
    """`_guarded` on one finished creative, with the offer and entry a bound deck would carry."""
    offer = copywrite._Offer(post=SourcePost(post_id="p1", url="u", author="@creator1", views=1,
                                             caption="c", hooks=["h"]),
                             creator_identifiers=(collapse("Gbillington1"),))
    entry = PlanEntry(order=0, asset_id="d1", creative_format="carousel", platform="linkedin",
                      language="en", aspect_ratio="1:1", trend_key="t1", style_key="k")
    return copywrite._guarded(subject, entry, offer, make_run(log=log, **run_kwargs))


def test_the_seam_guards_the_deck_and_rewrites_both_sides_of_the_copy_object() -> None:
    """`slide_texts[i] is panel_map[i]["source_text"]` is the invariant every walk holds, so the
    seam re-reads the slide texts off the guarded rows rather than editing them separately — the
    two can never disagree. A withdrawn label leaves `refs` in the same breath."""
    log = Recorder()
    subject = written([row(1, "Latency fell 1.5% this quarter", "Latency fell 13.8% this quarter"),
                       row(2, f"{COMMIT_LINE}\nThe agent writes its own tests")])

    earned = guarded_seam(subject, log=log)

    assert subject.copyset.slide_texts == ["Latency fell 13.8% this quarter",
                                           "The agent writes its own tests"]
    assert [r["source_text"] for r in subject.source.panel_map] == subject.copyset.slide_texts
    assert [tag.value for tag in earned] == ["copy_digit_drift"]
    assert "slide_1" not in subject.source.refs, "the replaced row's label was withdrawn"
    assert subject.source.refs["slide_2"] == "P1.panel.2", "the scrubbed row still quotes its panel"
    assert "Latency fell 13.8% this quarter" in subject.quoted, \
        "the verifier audits what actually ships"
    assert {"copy_digit_drift", "panel_identity_scrubbed"} <= {e for e, _, _ in log.warnings}


def test_the_seam_reads_the_runs_brand_marks_for_the_bound_post_alone() -> None:
    """`brand_marks` is keyed by POST because the vision pass's reading is a property of the SOURCE
    DECK, and two siblings bound to one post must see one reading of it. Another post's marks are
    not this deck's vocabulary."""
    log = Recorder()
    subject = written([row(1, TOTE_BAG), row(2, "The bag was not the point of the slide")])

    guarded_seam(subject, log=log, brand_marks={"p1": ["Opal Collection logo"], "p9": ["Notion"]})

    assert subject.copyset.slide_texts == ["", "The bag was not the point of the slide"]
    assert subject.source.panel_map[0]["chrome_watermark_stripped"] is True


def test_a_desynced_deck_skips_the_deck_half_loudly_and_still_guards_the_caption() -> None:
    """A deck whose rows and slide texts disagree is one this function has no honest way to guard:
    rewriting one side would silently re-map the other. So the deck half is skipped, the skip is
    on the console, and the CAPTION half runs regardless — it never depended on the panel map."""
    log = Recorder()
    subject = written([row(1, "28GB unified memory", "128GB unified memory")],
                      caption="I quit my job in March. My first client paid me in week two.",
                      slides=["something else entirely"])

    earned = guarded_seam(subject, log=log)

    assert subject.copyset.slide_texts == ["something else entirely"], "untouched, as promised"
    assert subject.source.panel_map[0]["source_text"] == "28GB unified memory"
    assert [tag.value for tag in earned] == ["caption_voice_review"]
    assert log.warned("panel_map_desynced"), "a skipped guard is never a silent one"


# ---------------------------------------------------------- the four walks, end to end


async def test_the_verbatim_walk_reaches_the_guards() -> None:
    """FR-304's mapping is arithmetic, so its rows can still carry a commit line the source deck
    wrote onto its own slide — layer 3 removes the CREATOR's identity, not everybody's."""
    log = Recorder()
    trend = make_trend(post(1, panels=(f"{COMMIT_LINE}\nThe agent now writes its own tests",
                                       "A perfectly ordinary second panel"),
                            caption="A caption long enough to be a caption at all."))
    call = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})

    result = await copywrite.write_copy([deck_entry(slides=2)], call=call, log=log, **context(
        trends={"t1": trend}, styles={"flat-card": deck_style()}))

    rows = result.provenance["d1"].panel_map
    assert result.copy["d1"].slide_texts == ["The agent now writes its own tests",
                                             "A perfectly ordinary second panel"]
    assert [r["identity_scrubbed"] for r in rows] == [True, False]
    assert rows[0]["source_text_original"].startswith(COMMIT_LINE)
    assert log.warned("panel_identity_scrubbed")


async def test_the_compressed_walk_reaches_the_guards() -> None:
    """A compressed line is the model's own bytes, and this is where an OCR confusable is BORN —
    the model retypes a panel it read as `I6GB`. Guard 1 heals it against the panel the compression
    was made from, and the row stays a compression."""
    log = Recorder()
    trend = compress_deck("The machine ships with 16GB of unified memory and eight cores.",
                          "The second page, at the length a real slideshow page carries.")
    call = StubCall({"d1": compressed(slide_texts=["I6GB of unified memory", "Page two, short"])})

    result = await copywrite.write_copy([deck_entry(slides=2)], call=call, log=log,
                                        carousel_copy_mode="compress",
                                        **context(trends={"t1": trend},
                                                  styles={"flat-card": deck_style()}))

    rows = result.provenance["d1"].panel_map
    assert result.copy["d1"].slide_texts == ["16GB of unified memory", "Page two, short"]
    assert [r["compressed"] for r in rows] == [True, True], "a repair is not a lost compression"
    assert log.warned("panel_digits_repaired")
    assert all({"identity_scrubbed", "chrome_watermark_stripped"} <= set(r) for r in rows)


async def test_the_auto_walk_reaches_the_guards() -> None:
    """D62's splice: the rows that fitted keep their verbatim bytes, and only the overflowing one
    took the call. A fabricated number in the spliced row restores the whole source panel and
    un-marks the row as compressed — it is not a compression any more."""
    log = Recorder()
    long_panel = ("Latency fell 13.8% this quarter across every region we measured, and the "
                  "second half of the sentence is here purely to carry it over the slide budget "
                  "that the style declares for this deck, which it now comfortably does.")
    trend = compress_deck(long_panel, "A short second page.")
    call = StubCall({"d1": compressed(slide_texts=["Latency fell 1.5% this quarter", ""])})

    result = await copywrite.write_copy([deck_entry(slides=2)], call=call, log=log,
                                        carousel_copy_mode="auto",
                                        **context(trends={"t1": trend}, styles={
                                            "flat-card": make_style(
                                                max_onimage_chars={"headline": 90, "subline": 60,
                                                                   "slide": 90})}))

    rows = result.provenance["d1"].panel_map
    assert rows[0]["source_text"] == long_panel, "the source panel, not the model's number"
    assert rows[0]["compressed"] is False and rows[1]["source_text"] == "A short second page."
    assert DegradationTag.COPY_DIGIT_DRIFT in result.tags["d1"]
    assert log.warned("copy_digit_drift")


async def test_the_translated_walk_reaches_the_guards_and_never_restores_german() -> None:
    """The translation carve-out at the seam: the token surgery still applies in full (a numeral
    means the same thing in every language), but a row the guards throw away goes WORDLESS rather
    than back into the language the operator asked us to translate out of."""
    log = Recorder()
    trend = german_trend("Die Latenz fiel im letzten Quartal um 13,8 Prozent.",
                         "Eine kurze zweite Seite.")
    call = SchemaCall({"copy_translated": {"d1": translated(slide_texts=[
        "Latency fell 1.5 percent last quarter.", "A short second page."])}})

    result = await copywrite.write_copy([foreign_deck(slides=2)], call=call, log=log,
                                        copy_language_mode="target",
                                        **context(trends={"t1": trend},
                                                  styles={"flat-card": deck_style()}))

    rows = result.provenance["d1"].panel_map
    assert rows[0]["source_text"] == "", "wordless, never the German bytes"
    assert rows[0]["source_text_original"].startswith("Die Latenz"), "the evidence stays German"
    assert rows[0]["translated"] is False, "a row that ships nothing is no translation"
    assert rows[1]["source_text"] == "A short second page.", "the clean row is untouched"
    assert DegradationTag.COPY_DIGIT_DRIFT in result.tags["d1"]


async def test_every_row_of_every_walk_carries_the_two_new_keys() -> None:
    """D54's one-row-schema contract, extended by D65 and asserted across all four contracts.

    The keys are written by the guards, so "which walk built this row" must not decide whether a
    reader has to ask if they exist — `generate._panel_map`, the FR-309 gallery card and meta.yaml
    all read one schema. Written even on the rows nothing happened to, and on the wordless ones.
    """
    trend = make_trend(post(1, panels=("The machine ships with 16GB of memory and eight cores.",
                                       "A perfectly ordinary second panel"),
                            caption="A caption long enough to be a caption at all."))
    german = german_trend("Die Maschine hat 16GB Speicher und acht Kerne.",
                          "Eine ganz gewoehnliche zweite Seite.")
    tight = make_style(max_onimage_chars={"headline": 90, "subline": 60, "slide": 30})
    walks = {
        "verbatim": await copywrite.write_copy(
            [deck_entry(slides=2)], call=StubCall({"d1": selection(caption_ref="P1.caption")}),
            **context(trends={"t1": trend}, styles={"flat-card": deck_style()})),
        "compress": await copywrite.write_copy(
            [deck_entry(slides=2)], call=StubCall({"d1": compressed(
                slide_texts=["16GB, eight cores", "Page two"])}),
            carousel_copy_mode="compress",
            **context(trends={"t1": trend}, styles={"flat-card": deck_style()})),
        "auto": await copywrite.write_copy(
            [deck_entry(slides=2)], call=StubCall({"d1": compressed(
                slide_texts=["16GB, eight cores", ""])}),
            carousel_copy_mode="auto",
            **context(trends={"t1": trend}, styles={"flat-card": tight})),
        "translate": await copywrite.write_copy(
            [foreign_deck(slides=2)], call=SchemaCall({"copy_translated": {"d1": translated(
                slide_texts=["16GB of memory and eight cores.", "An ordinary second page."])}}),
            copy_language_mode="target",
            **context(trends={"t1": german}, styles={"flat-card": deck_style()})),
    }

    for walk, result in walks.items():
        rows = result.provenance["d1"].panel_map
        assert len(rows) == 2, f"{walk}: the deck still maps every position"
        for entry_row in rows:
            assert entry_row["identity_scrubbed"] is False, f"{walk}: written, and false by default"
            assert entry_row["chrome_watermark_stripped"] is False, f"{walk}: likewise"


# ------------------------------------------------------------------ the two degrade tiers


async def test_a_degraded_deck_is_guarded_like_any_other() -> None:
    """The whole reason there is ONE seam. `_mapped_fallback` is the branch a failed copy call
    lands on, and a corrupted row is no less an order for having arrived down the cheap path."""
    log = Recorder()
    trend = make_trend(post(1, panels=(f"{COMMIT_LINE}\nThe agent now writes its own tests",
                                       "A perfectly ordinary second panel"),
                            caption="A caption long enough to be a caption at all."))
    call = StubCall({}, fail_when=lambda ids: True)

    result = await copywrite.write_copy([deck_entry(slides=2)], call=call, log=log, **context(
        trends={"t1": trend}, styles={"flat-card": deck_style()}))

    assert DegradationTag.COPY_DEGRADED in result.tags["d1"]
    assert result.copy["d1"].slide_texts[0] == "The agent now writes its own tests"
    assert result.provenance["d1"].panel_map[0]["identity_scrubbed"] is True


async def test_the_last_resort_tier_ships_a_borrowed_caption_and_it_is_guarded_too() -> None:
    """The second degrade tier: FR-99's last resort, where the copy call failed on a creative with
    no panel map at all and the top post's caption ships verbatim in its place.

    That caption is somebody else's story arriving by the cheapest route in the module, and the
    voice audit is exactly as due on it as on a caption the model chose. There is no deck half to
    run — an image creative has no panel map — so this is the seam's caption half on its own.
    """
    log = Recorder()
    trend = make_trend(post(1, hooks=("A hook that fits",),
                            caption="I quit my job in March. My first client paid me in week two."))
    call = StubCall({}, fail_when=lambda ids: True)

    result = await copywrite.write_copy([entry("a1", 0)], call=call, log=log,
                                        **context(trends={"t1": trend}))

    assert result.copy["a1"].caption == (
        "I quit my job in March. My first client paid me in week two."), "verbatim, as FR-331 says"
    assert result.provenance["a1"].panel_map == [], "an image creative maps no panels"
    assert DegradationTag.COPY_DEGRADED in result.tags["a1"], "the tier it arrived down"
    assert DegradationTag.CAPTION_VOICE_REVIEW in result.tags["a1"]
    assert log.warned("caption_voice_review")


async def test_a_refused_creative_has_no_deck_and_no_borrowed_voice_to_report() -> None:
    """The burnt-post refusal ships the topic name alone — it may quote nothing at all — so there
    is no panel map to guard and no creator's voice in the caption to raise a hand about. The
    guards are still reached; they simply have nothing to say, and silence is the honest answer."""
    log = Recorder()
    trend = make_trend(post(1, panels=("Panel one", "Panel two"),
                            caption="I quit my job in March. My first client paid in week two."))
    call = StubCall({"d1": selection(caption_ref="P1.caption")})

    result = await copywrite.write_copy([deck_entry(slides=2)], call=call, log=log,
                                        burnt_post_ids=["p1"],
                                        **context(trends={"t1": trend},
                                                  styles={"flat-card": deck_style()}))

    assert result.provenance["d1"].panel_map == [], "nothing was quoted, so nothing was mapped"
    assert DegradationTag.CAPTION_VOICE_REVIEW not in result.tags["d1"]
    assert not log.warned("caption_voice_review")


async def test_an_override_briefs_caption_is_exempt_at_the_seam_too() -> None:
    """`quoted=offer.post is not None` at the call site: a brief binds no source post, so its
    first-person caption is the OPERATOR's voice and the tag would fire on our own house style."""
    log = Recorder()
    call = StubCall({"a1": free_text(caption="I built this in a weekend. My whole stack is three.",
                                     slide_texts=["One", "Two"])})

    result = await copywrite.write_copy(
        [PlanEntry(order=0, asset_id="a1", creative_format="carousel", platform="linkedin",
                   language="en", aspect_ratio="1:1", trend_key=None, style_key="flat-card",
                   slide_count=2, brief_name="b", brief_influence="override")],
        call=call, log=log,
        campaign_briefs={"b": Brief(name="b", description="d", influence="override")},
        **context())

    assert result.copy["a1"].caption == "I built this in a weekend. My whole stack is three."
    assert DegradationTag.CAPTION_VOICE_REVIEW not in result.tags.get("a1", ())
    assert not log.warned("caption_voice_review")


async def test_a_quoted_caption_is_tagged_and_still_ships_verbatim_end_to_end() -> None:
    """The FR-363 half the operator actually sees: the caption reaches `caption.txt` byte for byte
    and the tag reaches the console and the gallery card beside it."""
    log = Recorder()
    caption = "I quit my job in March. My first client paid me in week two. It compounds."
    trend = make_trend(post(1, panels=("Panel one", "Panel two"), caption=caption))
    call = StubCall({"d1": selection(caption_ref="P1.caption")})

    result = await copywrite.write_copy([deck_entry(slides=2)], call=call, log=log, **context(
        trends={"t1": trend}, styles={"flat-card": deck_style()}))

    assert result.copy["d1"].caption == caption, "not one character was rewritten"
    assert DegradationTag.CAPTION_VOICE_REVIEW in result.tags["d1"]
