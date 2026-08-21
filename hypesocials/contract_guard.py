"""CONTRACT GUARDS — the deterministic audit of a deck's panel map (FR-362/FR-363, D65).

Module contract
---------------
Purpose: take the rows a copy walk finished — verbatim, compressed, auto or translated, they all
end in the same `panel_map` shape — and refuse to let a corrupted row become the RENDER CONTRACT.
Every function here is pure: strings and dicts in, strings and dicts out, no I/O, no config, no
logging of its own. The caller emits the warnings this module hands back, so a guard that changed
something is always visible on the console (§ the observability mandate) without this module
holding a logger.

Public API
    `guard_deck(rows, *, asset_id, admits, …) -> GuardedDeck` — the whole ladder, in order.
    `guard_caption(caption, *, asset_id, …) -> GuardedCaption` — the caption's half of FR-363.
    …plus every predicate the two compose, exported because they are the unit-testable core and
    because a caller occasionally wants one of them on its own:
    `numeric_tokens` · `repair_token` · `token_drifted` · `guard_digits` · `content_words` ·
    `content_overlap` · `dedupe_lines` · `strip_lines_equal` · `scrub_identity` · `beheaded` ·
    `truncated_tail` · `mark_identifiers` · `first_person_starts` · `caption_voice_suspect` ·
    `unmapped_positions` · `duplicate_positions` · `best_rival` · `subject_marks`.

Why this module exists (the audit of 2026-08-21, D65)
-----------------------------------------------------
`panel_map.source_text` is not provenance. It is the CONTRACT: the render prompt quotes it, the
post-render critics demand it back off the frame, and `cover_pick` chooses a cover by how well the
frame carries it. So a corrupted row is not a cosmetic defect — it is an ORDER, and the renderer
obeys it. The audit found the engine issuing orders nobody would sign:

* `I6GB`, `I46K STARS`, `IOX`, `7OB`, `28GB` (for 128GB) rendered as pixels, with the RIGHT digits
  sitting on the same row's `source_text_original`. Nothing diffed the two.
* Rows carrying the previous row's compressed text while their own original sat one position up.
* `Gbillington1 merged commit 859bdce into dev`, `Clearform-Labs/tldr #125` and an incidental tote
  bag's `OPAL COLLECTION` locked in as REQUIRED verbatim text — so the renderer drew another
  person's identity, in our brand colour, because the contract told it to.
* A creator's watermark ("EVOLVING AI") promoted to a hero headline — and the cover picker then
  chose the frame that carried the bug BEST, because it was reading the same corrupted contract.
* Duplicate OCR lines (`Documents / Documents`) demanded, and critics failing frames for not
  printing the garbage twice.
* Panels with neither a row nor a drop reason: a deck of 12 shipped as a success of 10.

Doctrine
--------
1. **Deterministic and cheap.** No LLM is in this loop and none may be added to it. Everything
   here is a regex, a set intersection or a string compare; the whole ladder runs in microseconds
   per deck and costs $0, which is why it runs on EVERY path including the degrade tiers.
2. **The fallback is always the source's own bytes, and failing that, silence.** A guard never
   invents a replacement, never paraphrases, never trims to fit. It either restores what the
   source actually said (`source_text_original`) or leaves the slide wordless in its own position.
   FR-304's alignment is never broken to fix a row: the row stays, the position stays, only the
   words change.
3. **`source_text_original` is never rewritten.** It is the evidence. Every guard writes to
   `source_text` alone, and the gallery's "what they said / what we shipped" pair stays honest.
4. **A guard that fires is LOUD.** Each returns a `GuardWarning` naming the asset, the slides and
   what changed. Silence means the deck was clean, and that is the only thing silence may mean.
5. **The translation carve-out.** On a row whose words are a TRANSLATION (D63/FR-343), falling
   back to `source_text_original` would ship foreign bytes onto a deck the operator asked to be in
   their own language — a worse outcome than the defect being guarded. So on those rows the
   row-level fallbacks go WORDLESS instead of restoring, while the token-level digit surgery still
   applies in full: a numeral means the same thing in every language.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hypesocials.models import DegradationTag
#: `mark_name` peels the descriptors a vision pass staples onto a logo it saw ("Notion logo icon"
#: -> "Notion"); guard 9 joins on the PEELED form for the same reason `generate/carousel` does —
#: collapsing one side raw and the other peeled is how a join silently misses (`sources/mark_names`
#: was extracted to make that impossible). `sources/mark_names` imports nothing from this package,
#: so there is no cycle back into `sources` here.
from hypesocials.sources.mark_names import mark_name
from hypesocials.topic_filter import collapse

# ---------------------------------------------------------------------------------------------
# Guard 1 — digits (FR-362.1)
# ---------------------------------------------------------------------------------------------

#: The OCR confusables a vision pass produces on DIGITS, and the only substitutions guard 1 may
#: make. Deliberately one-directional: `I` can become `1` when the source says `1`, and `1` never
#: becomes `I` — a repair that could turn a real numeral into a letter would be inventing a word.
_CONFUSABLES = {"I": "1", "l": "1", "i": "1", "O": "0", "o": "0"}

#: The unit suffixes a measurement wears. `X` and `B` are in the list because `IOX` and `7OB` are
#: real defects from the audit; `%` is separate below because it takes no letter boundary after it.
_UNIT = (r"(?:%|(?:GB|MB|TB|KB|MS|PX|PT|HRS|HR|SEC|MIN|FPS|STARS|B|K|M|X)"
         r"(?![A-Za-z0-9]))")
#: A NUMERIC-ISH token: a run of digits and digit-confusable letters, optionally decimal-separated,
#: optionally wearing a unit. The confusable letters are inside the run on purpose — `IOX` carries
#: no digit at all and is still the number 10 — which means the pattern also matches innocent
#: all-`IlOo` words like `lol`. That is harmless by construction: a token with no digits is never
#: judged for drift, and it is only ever REPAIRED against an original token it matches
#: character-for-character outside the confusable positions.
_NUMERIC_TOKEN = re.compile(
    rf"(?<![A-Za-z0-9])[0-9IlOo]+(?:[.,][0-9IlOo]+)*(?:\s?{_UNIT})?(?![A-Za-z0-9])")

#: A one-character token is never repaired: the English pronoun `I` and a source panel's lone `1`
#: are the same shape, and healing one into the other would rewrite prose into arithmetic.
_MIN_REPAIRABLE = 2


@dataclass(slots=True, frozen=True)
class DigitFinding:
    """Guard 1's verdict on one row: the bytes to ship and what had to be done to get them."""

    #: The shipped text after repair and token-level restoration. Byte-identical to the input when
    #: `repaired`, `restored` and `row_replaced` are all empty/false.
    text: str
    #: `(shipped token, healed token)` for every OCR confusable guard 1 fixed. NOT a degradation —
    #: this is the repair working, and `ocr_repair`'s doctrine already sanctions it.
    repaired: tuple[tuple[str, str], ...] = ()
    #: `(shipped token, the original's token)` for every token whose DIGITS drifted and were put
    #: back. Earns `copy_digit_drift`.
    restored: tuple[tuple[str, str], ...] = ()
    #: True when a digit-bearing token had no counterpart in the original at all — the token
    #: structure differs too far for surgery, so the caller ships the whole original row.
    row_replaced: bool = False

    @property
    def drifted(self) -> bool:
        """Did anything here earn `copy_digit_drift`? A pure repair does not."""
        return bool(self.restored) or self.row_replaced


def numeric_tokens(text: str) -> list[re.Match[str]]:
    """Every numeric-ish token in `text`, as MATCHES — the spans are what a replacement needs."""
    return list(_NUMERIC_TOKEN.finditer(str(text or "")))


def digits_of(token: str) -> str:
    """`"1,5 %"` -> `"15"` — the digits alone, so a decimal comma and a point compare equal.

    A German panel writes `1,5 %` and its English translation writes `1.5%`; those are the same
    measurement and guard 1 must not report the separator as drift. Whitespace, units and
    separators all fall away here, and only the digit sequence is compared.
    """
    return "".join(char for char in str(token or "") if char.isdigit())


def repair_token(shipped: str, original: str) -> str | None:
    """`("I6GB", "16GB") -> "16GB"`; `None` when the two are not the same token misread.

    The test is total and unforgiving, which is what makes it safe to run unguarded over every
    row: the two tokens must be the same LENGTH, every character must either match exactly or be
    a sanctioned confusable standing where the original has a DIGIT. One character out of place —
    a different unit, an extra separator, a dropped leading digit — and this returns `None`, which
    hands the pair to the drift test below instead of quietly rewriting it.
    """
    shipped, original = str(shipped or ""), str(original or "")
    if len(shipped) < _MIN_REPAIRABLE or len(shipped) != len(original) or shipped == original:
        return None
    out: list[str] = []
    for mine, theirs in zip(shipped, original):
        if mine == theirs:
            out.append(mine)
        elif theirs.isdigit() and _CONFUSABLES.get(mine) == theirs:
            out.append(theirs)
        else:
            return None
    return "".join(out)


def token_drifted(shipped: str, original: str) -> bool:
    """True when these two are the SAME measurement written with different digits (`28GB`/`128GB`).

    A counterpart rather than a coincidence: both tokens have digits, they wear the same non-digit
    tail (`GB` and `GB`, `%` and `%`), and their digit sequences differ while still being close
    enough that one is plainly a misreading of the other — one is a prefix or a suffix of the
    other (the dropped-leading-digit class: `128` -> `28`), or they are the same length and differ
    in exactly one place (`146` -> `746`).

    Two numbers that are simply DIFFERENT — `1.5%` against `13.8%`, the pm3y fabrication class —
    fail this test deliberately. They are not a misreading of one another, there is no honest
    surgery to do, and the row-level fallback handles them.
    """
    mine, theirs = digits_of(shipped), digits_of(original)
    if not mine or not theirs or mine == theirs:
        return False
    if _tail(shipped) != _tail(original):
        return False
    if mine.startswith(theirs) or mine.endswith(theirs):
        return True
    if theirs.startswith(mine) or theirs.endswith(mine):
        return True
    return (len(mine) == len(theirs)
            and sum(1 for a, b in zip(mine, theirs) if a != b) == 1)


def _tail(token: str) -> str:
    """The unit a token wears, casefolded: `"146K"` -> `"k"`, `"1.5%"` -> `"%"`, `"128"` -> `""`.
    """
    return "".join(char for char in str(token or "")
                   if not char.isdigit() and not char.isspace()
                   and char not in ".,").casefold()


def guard_digits(shipped: str, original: str) -> DigitFinding:
    """FR-362 guard 1 — heal the OCR confusables, put back the digits that drifted, in one pass.

    Three outcomes per numeric token of the SHIPPED text, decided against the tokens of that row's
    own `source_text_original` and nothing else:

    1. **It is already there.** The token appears verbatim among the original's tokens: it is the
       source's own number and nothing happens to it. Every verbatim row lands here for every
       token, which is why this guard is free on the path that carries most decks.
    2. **It is a misreading.** `repair_token` matches it to an original token character for
       character outside the confusable positions — `I6GB`/`16GB`, `IOX`/`10X`, `7OB`/`70B` — and
       the healed bytes ship. This is a REPAIR, not a degradation: `ocr_repair`'s doctrine already
       sanctions exactly this substitution at admission, and the row was corrupted downstream of
       it (by a compression, a transcription or a translation).
    3. **Its digits drifted.** `token_drifted` finds the counterpart it was written from and the
       digits disagree — `28GB` where the source says `128GB`. The ORIGINAL's bytes ship in that
       token's place and the row earns `copy_digit_drift`. There is no third option here: a number
       on a slide is a claim about the world, and shipping a claim the source never made is the
       one thing the verbatim contract exists to prevent.

    A digit-bearing token with NO counterpart at all is the fourth case and it is not a token
    problem — the row has numbers the source never wrote. `row_replaced` says so and the caller
    ships the whole original panel instead.
    """
    shipped, original = str(shipped or ""), str(original or "")
    if not shipped.strip():
        return DigitFinding(shipped)
    originals = [match.group(0) for match in numeric_tokens(original)]
    exact = set(originals)
    repaired: list[tuple[str, str]] = []
    restored: list[tuple[str, str]] = []
    unmatched = False
    out: list[str] = []
    cursor = 0
    for match in numeric_tokens(shipped):
        token = match.group(0)
        replacement = token
        if token not in exact:
            healed = next((fixed for candidate in originals
                           if (fixed := repair_token(token, candidate)) is not None), None)
            if healed is not None:
                replacement = healed
                repaired.append((token, healed))
            elif (counterpart := next(
                    (candidate for candidate in originals if token_drifted(token, candidate)),
                    None)) is not None:
                replacement = counterpart
                restored.append((token, counterpart))
            elif any(digits_of(token) and digits_of(token) == digits_of(candidate)
                     for candidate in originals):
                # A SEPARATOR variant, not drift (D65 fix). A German panel writes `1,5 %` and its
                # translation writes `1.5%`; `digits_of`'s whole reason to exist is that those are
                # one measurement. The ladder above compares raw strings, so the pair reaches here
                # unmatched — and before this rung it set `unmatched`, which on a TRANSLATED row
                # (never restorable to source-language bytes) blanked a perfectly good slide over
                # a comma. The digits agree; the row ships as written.
                replacement = token
            elif digits_of(token):
                unmatched = True
        out.append(shipped[cursor:match.start()])
        out.append(replacement)
        cursor = match.end()
    out.append(shipped[cursor:])
    return DigitFinding("".join(out), tuple(repaired), tuple(restored), unmatched)


# ---------------------------------------------------------------------------------------------
# Guard 2 — row alignment (FR-362.2)
# ---------------------------------------------------------------------------------------------

#: Below this share of shared content words, a row's shipped text is not a rendering of its own
#: source panel at all. Start value from the D65 plan; tuned against 4344's `Ig_08`, whose
#: misaligned rows share nothing but stopwords with their own originals.
ALIGNMENT_FLOOR = 0.3
#: How strongly ANOTHER row's source panel has to explain a row's words before guard 2 believes
#: the two slipped. Higher than the floor above on purpose: "this does not look like its own
#: panel" is a suspicion, "this is plainly a rendering of panel 3" is a finding, and only the
#: second is worth moving bytes over.
_RIVAL_FLOOR = 0.6
#: Below this many content words on either side, a containment ratio is noise rather than evidence
#: — two four-word lines from one deck share a word by accident all the time. Guard 2 simply does
#: not look at rows that short; they are also the rows a misalignment is least able to damage.
_MIN_COMPARABLE_WORDS = 4
#: A "content word" has to be long enough to mean something. Three characters keeps `AI`, `UI`
#: and `5x` out of the arithmetic — those match across unrelated panels of the same deck and
#: would flatter a misaligned row into looking aligned.
_CONTENT_WORD_MIN = 3
_WORD = re.compile(r"[^\W_]+")


def content_words(text: str) -> set[str]:
    """The casefolded words of `text` worth comparing — a set: order is not the question."""
    return {word for word in _WORD.findall(str(text or "").casefold())
            if len(word) >= _CONTENT_WORD_MIN}


def content_overlap(shipped: str, original: str) -> float:
    """How much of the SMALLER text's vocabulary the two share — 1.0 identical, 0.0 unrelated.

    Containment (`|A ∩ B| / min(|A|, |B|)`), not Jaccard, and the difference decides whether this
    guard is usable at all. A compressed row is a 90-character summary of an 800-character panel:
    its words are almost all drawn FROM that panel, but the union is enormous, so Jaccard reads
    ≈ 0.08 — under any floor worth having — and a Jaccard guard would un-compress every deck the
    operator asked to be compressed. Containment reads ≈ 1.0 for the same row, because every word
    the compression kept came from the original, and it still reads ≈ 0.0 for the defect this
    guard exists to catch: a row carrying a DIFFERENT panel's words shares nothing with its own.

    Either side empty is `1.0` — "nothing to judge" is not "misaligned", and a wordless row is
    already handled by FR-304's drop reasons.
    """
    mine, theirs = content_words(shipped), content_words(original)
    if not mine or not theirs:
        return 1.0
    return len(mine & theirs) / min(len(mine), len(theirs))


def best_rival(shipped: str, originals: Sequence[str], index: int) -> tuple[int, float]:
    """`(the 1-based row that explains these words better than their own, its overlap)`.

    The second half of guard 2, and the half that makes it usable. "This row's words do not look
    like its own source panel" is far too weak a test on its own: a compression is ALLOWED to
    paraphrase, and a humanised 90-character line drawn from an 800-character panel can honestly
    share very little vocabulary with it. Firing on that alone would un-compress decks the
    operator asked to be compressed — the exact over-reach the first draft of this guard made.

    What is NOT ambiguous is a row whose words match a DIFFERENT row's source panel better than
    their own. That is what a deck whose rows slipped by one position looks like from the inside
    (run 4344's `Ig_08`: slides 4, 6 and 8 carried the previous repo's compressed text while the
    right text sat one row up), and no paraphrase produces it. So the guard needs both halves —
    a poor fit at home AND a better home elsewhere — before it touches a row.

    `(0, 0.0)` when no other row explains it better, which is the answer that leaves the row alone.
    """
    best, score = 0, 0.0
    if len(content_words(shipped)) < _MIN_COMPARABLE_WORDS:
        return best, score
    for other, original in enumerate(originals):
        if other == index or len(content_words(original)) < _MIN_COMPARABLE_WORDS:
            continue
        overlap = content_overlap(shipped, original)
        if overlap > score:
            best, score = other + 1, overlap
    return best, score


def duplicate_positions(rows: Sequence[Mapping[str, Any]]) -> list[int]:
    """The row INDEXES (0-based) whose `source_position` a previous row already claimed.

    Two rows pointing at one source panel means the deck is telling the gallery that two of our
    slides render the same slide of theirs, which is FR-304's alignment broken at the root. The
    FIRST claim wins — it is the one the walk built in order — and every later one is realigned.
    """
    seen: set[int] = set()
    out: list[int] = []
    for index, row in enumerate(rows):
        position = _int(row.get("source_position"))
        if position and position in seen:
            out.append(index)
        elif position:
            seen.add(position)
    return out


# ---------------------------------------------------------------------------------------------
# Guard 3 — duplicate lines (FR-362.3)
# ---------------------------------------------------------------------------------------------


def dedupe_lines(text: str) -> tuple[str, list[str]]:
    """`(the text with repeated LINES collapsed, the lines that went)` — exact matches only.

    `Audio / Documents / Documents / AI` is what a vision pass produces when a source slide's
    list renders one row twice; shipped into the contract it becomes an ORDER to print the
    duplicate, and the post-render critics then fail the frame for obeying it only once.

    Exact equality after `strip()`, casefolded, and nothing looser: two lines that merely start
    the same way are two lines. The FIRST occurrence keeps its bytes and its position — surviving
    lines are the original strings, never re-joined tokens, exactly as `_strip_creator_lines` does
    upstream — and blank lines are never deduped, because a blank line is spacing rather than
    content and a panel's shape is part of what it says.
    """
    text = str(text or "")
    if "\n" not in text:
        return text, []
    seen: set[str] = set()
    kept: list[str] = []
    dropped: list[str] = []
    for line in text.split("\n"):
        key = line.strip().casefold()
        if not key:
            kept.append(line)
            continue
        if key in seen:
            dropped.append(line.strip())
            continue
        seen.add(key)
        kept.append(line)
    if not dropped:
        return text, []
    while kept and not kept[0].strip():
        kept.pop(0)
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept), dropped


# ---------------------------------------------------------------------------------------------
# Guards 4 and 9 — identity and watermark chrome (FR-362.4 / FR-362.7)
# ---------------------------------------------------------------------------------------------

#: A commit line: `Gbillington1 merged commit 859bdce into dev`. The whole line goes — it names a
#: person, a repository and a hash, none of which are OUR creative's content, and no part of it
#: survives editing into a sentence somebody would want to read.
_COMMIT_LINE = re.compile(
    r"(?i)\b(?:merged|pushed|committed|reverted|cherry-picked)\s+commit\s+[0-9a-f]{6,40}\b")
#: A bare `owner/repo`, optionally with its issue or PR number: `Clearform-Labs/tldr #125`. Only
#: when the LINE is that reference and nothing else — `github.com/user/repo` inside a terminal
#: block is the content of that slide (FR-319 as amended) and this must never touch it.
_REPO_REF_LINE = re.compile(r"(?i)^[@\s]*[\w.-]{2,}/[\w.-]{2,}(?:\s*#\d+)?[\s.,:;·|]*$")
#: A bare issue or PR reference on a line of its own: `#125`.
_ISSUE_REF_LINE = re.compile(r"^[\s]*#\d+[\s.,:;·|]*$")
#: The words a line has to open with to read as a subjectless CONTINUATION of the line that was
#: just removed — the "beheaded row" shape. Kept short and English-only on purpose: it is a
#: tie-breaker on top of the case test below, not a grammar.
_CONTINUATION = ("and ", "but ", "so ", "or ", "then ", "which ", "that ", "to ", "with ")


@dataclass(slots=True, frozen=True)
class IdentityFinding:
    """Guards 4 and 9's verdict on one row: what survives, what went, and under which flag."""

    text: str
    #: Lines dropped as somebody's IDENTITY — a creator handle, a commit, a repo or issue
    #: reference. Rides `panel_map.identity_scrubbed`.
    identity: tuple[str, ...] = ()
    #: Lines dropped as CHROME — a watermark or brand mark the source stamped on its own slide.
    #: Rides `panel_map.chrome_watermark_stripped`, the sibling of `chrome_counter_stripped`.
    chrome: tuple[str, ...] = ()
    #: True when the removal took the row's LEADING clause and what remains reads as a fragment of
    #: it. The caller ships nothing rather than the orphan.
    beheaded: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.identity or self.chrome)


def strip_lines_equal(text: str, identifiers: Iterable[str]) -> tuple[str, list[str]]:
    """`(the text without the lines that EQUAL an identifier, the lines that went)` — pure.

    The mechanics of `copywrite._strip_creator_lines` (FR-312), lifted here so that one rule
    serves both callers: a line is dropped iff its own COLLAPSED form (casefolded, alphanumerics
    only) equals one of `identifiers`, which are already collapsed. Never a substring test —
    "labs" contains "lab", every second English hook contains something, and a substring rule
    would quietly shred the verbatim contract.

    Everything that survives survives byte for byte; only blank lines orphaned at the very top or
    bottom by the removal go with it. A text that matched nothing comes back as the same object,
    which is what keeps this safe to run over every row of every deck.
    """
    text = str(text or "")
    if not text or not identifiers:
        return text, []
    lookup = set(identifiers)
    lines = text.split("\n")
    dropped = [line for line in lines if collapse(line) in lookup]
    if not dropped:
        return text, []
    kept = [line for line in lines if collapse(line) not in lookup]
    while kept and not kept[0].strip():
        kept.pop(0)
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept), [line.strip() for line in dropped]


def mark_identifiers(marks: Iterable[str], sanctioned: Iterable[str] = ()) -> set[str]:
    """The collapsed forms of the brand marks a row may NOT simply reprint as its own words.

    `marks` is the vision pass's `brand_marks` for the deck (FR-306) — every logo, wordmark and
    watermark it could see, in the free-form way it wrote them down ("Notion logo icon"). Each
    yields TWO keys: the raw string collapsed, and its `mark_name` peeled first and then collapsed,
    because a row reads `OPAL COLLECTION` while the vision pass wrote `Opal Collection logo` and
    the join has to survive that. Peeling both sides is the discipline `sources/mark_names`
    exists to enforce.

    `sanctioned` is the subset the render side is entitled to DRAW — the tool logo the panel was
    actually about, joined to an actually-cropped patch (FR-315). Those are removed here, because a
    slide whose one line is the product it is about is a legitimate slide. It is the SEAM rather
    than a live channel today: at copy time nothing has been cropped yet, so the copy stage passes
    nothing and the deck-subject test in `guard_deck` does the discriminating instead.

    Anything shorter than the creator-identifier floor is discarded for the same reason FR-312
    discards it: a two-character collapsed form matches half of every deck.
    """
    keep_out = {folded for mark in sanctioned
                for folded in (collapse(mark), collapse(mark_name(str(mark or "")))) if folded}
    return {folded for mark in marks
            for folded in (collapse(mark), collapse(mark_name(str(mark or ""))))
            if len(folded) >= 3 and folded not in keep_out}


def subject_marks(rows: Sequence[Mapping[str, Any]], marks: Iterable[str]) -> set[str]:
    """The marks this deck is ABOUT, which guard 9 must therefore leave alone.

    The discriminator the copy stage can afford, and the answer to the one real risk in guard 9:
    `OPAL COLLECTION` off an incidental tote bag and `Notion` off the tool a SaaS-tour deck is
    reviewing are the same shape — a row that is nothing but somebody's wordmark — and stripping
    the second would cost that slide its subject.

    They differ in the rest of the deck. A mark the deck is ABOUT is written into its other
    panels' sentences ("Notion replaced my docs"); a watermark or an incidental logo appears
    nowhere but on its own line. So a mark whose collapsed form is found inside the collapsed text
    of some OTHER row — a row that is not itself just that mark — is deck subject matter and is
    exempt.

    Rows that ARE the mark are excluded from the corpus on purpose: a watermark stamped on three
    slides would otherwise vouch for itself three times over. **That exclusion is per LINE, not per
    row (D65 fix).** Testing the whole row was the same self-vouching bug wearing a hat: the
    audit's real shape is a watermark carried as a row PREFIX — the mark on its own opening line
    with the slide's real sentence under it — whose collapsed ROW is not equal to the mark, so it
    entered the corpus, found its own
    watermark there and declared it deck subject matter. Guard 9 then left the hero line standing,
    which is exactly how `EVOLVING AI` was promoted to a headline on a published slide. A line
    that is nothing but the mark never vouches for it, wherever in its row it sits; only the rest
    of the deck's prose can.
    """
    lookup = {folded for folded in marks if folded}
    if not lookup:
        return set()
    corpus = " | ".join(
        collapse(line) for row in rows for line in str(row.get("source_text") or "").splitlines()
        if collapse(line) and collapse(line) not in lookup)
    return {folded for folded in lookup if folded in corpus}


def beheaded(before: str, after: str) -> bool:
    """True when a strip took the row's OPENING line and left a fragment of the sentence behind.

    Run 1zqv shipped `ran the cheap experiment you asked for.` — a slide whose subject was the
    creator's handle on the line above, which layer 3 correctly removed and which left an order to
    render a sentence with no subject. The test is narrow on purpose: it fires only when the
    removed line was the FIRST one, and only when what now leads reads as a continuation — it
    opens lower-case, or on a conjunction. Source on-image text is overwhelmingly title-cased or
    sentence-cased, so a row that now opens lower-case is a row that used to open somewhere else.

    A row that lost a MIDDLE or TRAILING line is never beheaded: whatever leads it still leads it.
    """
    before, after = str(before or ""), str(after or "")
    if not after.strip() or not before.strip():
        return False
    if before.split("\n")[0].strip() == after.split("\n")[0].strip():
        return False  # the opening line survived — nothing was decapitated
    head = next((line.strip() for line in after.split("\n") if line.strip()), "")
    if head.casefold().startswith(_CONTINUATION):
        return True
    first = next((char for char in head if char.isalpha()), "")
    return bool(first) and first.islower()


def scrub_identity(text: str, *, identifiers: Iterable[str] = (),
                   marks: Iterable[str] = ()) -> IdentityFinding:
    """FR-362 guards 4 and 9 — take every OTHER party's identity off the row before it is an order.

    Four line-level rules, and the fact that they are all LINE-level is the design, not a
    shortcut. `compress_scrub` upstream states the same rule for the same reason: "the line is
    removed whole rather than edited — a compressed sentence with its mark cut out is a sentence
    nobody wrote and nobody proof-read". A `#125` deleted out of the middle of a clause leaves a
    clause the renderer will still print, and print wrong.

    1. **Creator identity** (`identifiers`, already collapsed by the caller): the handle, the
       display name, the deck's own chrome. `_strip_creator_lines`' rule, re-run here because a
       guard that RESTORED `source_text_original` restored the pre-layer-3 bytes with it.
    2. **Commit lines** — `Gbillington1 merged commit 859bdce into dev`.
    3. **Bare repository and issue references** — `Clearform-Labs/tldr #125`, `#125`. Only when
       the line is that and nothing else; a technical URL inside a sentence is content (FR-319).
    4. **Brand marks** (`marks`, collapsed, sanctioned ones already removed by the caller): a line
       that IS somebody's wordmark — `OPAL COLLECTION` off an incidental tote bag, `EVOLVING AI`
       off the creator's own watermark — is chrome, exactly like the page counter `_strip_counter_
       lines` takes out, and it rides its own flag for the same reason: a watermark is nobody's
       brand of ours, and it must not tag the creative `competitor_stripped`.

    Rule 4's finding is reported separately (`chrome`) from rules 1–3 (`identity`) because the two
    answer different questions on the gallery card — "we nearly named another account" versus "we
    nearly reprinted their furniture" — and each has its own `panel_map` flag.
    """
    text = str(text or "")
    if not text.strip():
        return IdentityFinding(text)
    before = text
    identity: list[str] = []
    text, dropped = strip_lines_equal(text, identifiers)
    identity.extend(dropped)
    kept: list[str] = []
    for line in text.split("\n"):
        bare = line.strip()
        if bare and (_COMMIT_LINE.search(bare) or _REPO_REF_LINE.match(bare)
                     or _ISSUE_REF_LINE.match(bare)):
            identity.append(bare)
            continue
        kept.append(line)
    if len(kept) != len(text.split("\n")):
        while kept and not kept[0].strip():
            kept.pop(0)
        while kept and not kept[-1].strip():
            kept.pop()
        text = "\n".join(kept)
    text, chrome = strip_lines_equal(text, marks)
    return IdentityFinding(text, tuple(identity), tuple(chrome),
                           beheaded(before, text) if identity or chrome else False)


# ---------------------------------------------------------------------------------------------
# Guard 5 — truncation (FR-362.5)
# ---------------------------------------------------------------------------------------------

#: A row that ends on one of these is not finished: an opening bracket with nothing inside it, or
#: a trailing comma with nothing after it. Both are the audit's own fixtures (`( src/types/in`).
#: Deliberately SHORT. A colon and a hyphen are not here and must not be added: "The 3 tools:" and
#: "all-in-one —" are how source panels legitimately end, and gating on them would blank slides
#: that say exactly what their author meant them to say.
#: The hanging hyphen goes here too — `develop-` at the end of a row is a word cut in half, and
#: unlike an ellipsis it is never authored. It has to be ATTACHED to a word character: "all-in-one
#: —" ends on a spaced em dash, which is punctuation a person chose, and must not match.
_DANGLING_TAIL = re.compile(r"(?:[(\[{,]|\w[-‐‑])$")
#: A list marker whose item never arrived — the LAST line of the row is nothing but `3.`. Anchored
#: to its own line on purpose: "Ship it in step 3." is a finished sentence that happens to end on
#: a numeral, and only a marker standing alone is evidence of anything.
_DANGLING_MARKER = re.compile(r"(?:\A|\n)[ \t]*(\d{1,2}\.)[ \t]*\Z")


def truncated_tail(text: str) -> str:
    """The cut-looking tail of `text`, or `""` — the cheap end-of-row half of guard 5.

    Deliberately NOT a second copy of `ocr_repair.truncation_suspect`: that one owns the
    ellipsis/hanging-hyphen/mid-word family and its answer already rides the row as
    `truncation_suspect`. This one owns the two shapes that function does not look at — a line
    that stops on an opening bracket or a comma, and a list marker whose item never arrived — and
    the caller ORs the two.
    """
    stripped = str(text or "").rstrip()
    if not stripped:
        return ""
    if match := _DANGLING_TAIL.search(stripped):
        return match.group(0)
    if marker := _DANGLING_MARKER.search(stripped):
        return marker.group(1)
    return _unclosed(stripped)


def _unclosed(text: str) -> str:
    """`"("` when a bracket opens in `text` and never closes — the audit's own truncation shape.

    The 1zqv fixture is a body panel ending `( src/types/in`: the parenthesis opened, the path
    inside it was cut off mid-word, and `ocr_repair.truncation_suspect` cannot see it (the line is
    under its 60-character floor and `in` is under its 4-character token floor). An open bracket
    with no partner is unambiguous in a way a trailing word never is — a source author does not
    write half a parenthesis — so it is worth its own test rather than a loosening of that one.

    Counted over the whole row, not the last line, because the cut can take the closing bracket
    and the two lines after it. Only OPENS-without-closes count: a stray `)` is a typo, not a cut.
    """
    for opener, closer in (("(", ")"), ("[", "]"), ("{", "}")):
        if text.count(opener) > text.count(closer):
            return opener
    return ""


# ---------------------------------------------------------------------------------------------
# Guard 6 — coverage (FR-362.6)
# ---------------------------------------------------------------------------------------------


def unmapped_positions(rows: Sequence[Mapping[str, Any]], source_panel_count: int) -> list[int]:
    """The source panels this deck neither mapped nor dropped — the silent losses, only those.

    The ceiling is `min(source_panel_count, len(rows))`, and that clamp is the whole subtlety.
    A source deck LONGER than the platform's carousel maximum is truncated at ASSIGN (§0.4′): its
    tail panels have no row because nobody bought them, the deck is tagged `panels_truncated`, and
    the operator was told at the Confirm gate. Counting those as losses here would print a scary
    warning about a decision the plan made on purpose. What is left after the clamp is the real
    question: inside the range the walk was supposed to cover, is every position accounted for?

    Every row the walks build carries a `drop_reason` (`""` when it shipped), so "has a row" and
    "has a recorded drop reason" are the same test — a position with a row is explained either
    way. A position with no row at all is the defect: run 4344's `Ig_02` lost source panels 11–12
    with no row, no reason and a `status: success`.
    """
    ceiling = min(_int(source_panel_count), len(rows))
    mapped = {_int(row.get("source_position")) for row in rows}
    return [position for position in range(1, ceiling + 1) if position not in mapped]


# ---------------------------------------------------------------------------------------------
# Guard 8 — caption voice (FR-363)
# ---------------------------------------------------------------------------------------------

#: Sentence boundaries for the voice heuristic — terminal punctuation or a line break, the same
#: split `copywrite._sentences` uses on captions.
_SENTENCE = re.compile(r"(?<=[.!?…])\s+|\n+")
#: The openings that make a sentence the SOURCE CREATOR's own story rather than a statement about
#: the subject. English-only and first-person-singular only: "we" is how a company writes about
#: itself and is not the defect, and a plural "our" caption reads as ours because it is.
_FIRST_PERSON = ("i ", "i'm ", "i've ", "i'll ", "i'd ", "im ", "my ", "me ", "mine ",
                 "i,", "i.", "i!", "i?")
#: Two first-person sentence openings, or three in ten, is a caption written in somebody else's
#: voice. One is a turn of phrase and stays silent — an audit that fires on every caption is an
#: audit the operator learns to skip.
_VOICE_MIN_STARTS = 2
_VOICE_DENSITY = 0.30


def first_person_starts(caption: str) -> tuple[int, int]:
    """`(sentences opening in the first person singular, sentences)` — the raw counts, for the log.

    The test is on the OPENING of a sentence, never on the whole of it: "the tool I use every day"
    is a statement about the tool, while "I use this every day" is a statement about the author.
    Only the first shape can turn our account into somebody else's diary.
    """
    sentences = [part.strip() for part in _SENTENCE.split(str(caption or "")) if part.strip()]
    hits = sum(1 for sentence in sentences
               if sentence.casefold().startswith(_FIRST_PERSON) or sentence.casefold() == "i")
    return hits, len(sentences)


def caption_voice_suspect(caption: str) -> bool:
    """FR-363 — does this caption read as the SOURCE creator's first-person voice?

    A caption is quoted verbatim (FR-331) and that is not in question here: run 4344 published a
    creator's own life story — "I quit my job", "my first client" — under our account, word for
    word, exactly as the contract says to. The words are right and the VOICE is wrong, and no
    deterministic rule can tell the operator which one they want. So this only ever raises a hand.
    """
    hits, total = first_person_starts(caption)
    if not total or not hits:
        return False
    return hits >= _VOICE_MIN_STARTS or (hits / total) >= _VOICE_DENSITY


# ---------------------------------------------------------------------------------------------
# The composites — the ladder, in order, with its receipts
# ---------------------------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class GuardWarning:
    """One thing a guard changed, ready for the caller's `_warn` — never logged from here.

    The guards are pure and the log is I/O, so this module RETURNS its warnings and the copy stage
    emits them through the same `_warn` every other copy-side finding goes through. That keeps
    `contract_guard` testable without a fake logger and keeps one console vocabulary.
    """

    event_type: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class GuardedDeck:
    """What the ladder made of one deck: new rows, new slide texts, tags and warnings."""

    #: One NEW dict per input row, same order, same count, same positions — plus the two D65 keys
    #: on every row. The input rows are never mutated: `CopyProvenance` is the caller's data.
    rows: tuple[dict[str, Any], ...] = ()
    #: `rows[i]["source_text"]`, extracted for the caller's `CopySet.slide_texts`. The two are the
    #: same strings by construction, and keeping them that way is the invariant every walk holds.
    texts: tuple[str, ...] = ()
    #: Every string a guard PUT on a slide. It joins the verifier's quoted pool for the same
    #: reason `_auto`'s compressed lines do: a restored original is not a quote gone missing, and
    #: reporting it as `copy_not_verbatim` would bury the rows where that check still has teeth.
    authored: tuple[str, ...] = ()
    tags: tuple[DegradationTag, ...] = ()
    warnings: tuple[GuardWarning, ...] = ()
    #: Slot names (`slide_3`) whose ref label the ladder had to withdraw — the row no longer ships
    #: the bytes that label claims. The caller drops them from `CopyProvenance.refs`.
    dropped_refs: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.tags or self.warnings)


@dataclass(slots=True, frozen=True)
class GuardedCaption:
    """FR-363's half: the caption after its identity scrub, plus the voice hand-raise."""

    caption: str = ""
    tags: tuple[DegradationTag, ...] = ()
    warnings: tuple[GuardWarning, ...] = ()
    #: True when the scrub rewrote the caption, so the caller can add it to the verifier's pool.
    scrubbed: bool = False


def guard_deck(
    rows: Sequence[Mapping[str, Any]],
    *,
    asset_id: str,
    admits: Callable[[str], bool],
    identifiers: Iterable[str] = (),
    marks: Iterable[str] = (),
    source_panel_count: int = 0,
) -> GuardedDeck:
    """FR-362 — run the whole guard ladder over one finished deck and report what it changed.

    Args:
        rows: the walk's `panel_map`, one row per OUR slide, in slide order. Never mutated.
        asset_id: for the warnings — the operator reads them per creative.
        admits: `text -> may this string ship on a slide`. The copy stage passes its own
            `_panel_verdict` gate, so a restored original faces exactly the admission test the
            walk applied in the first place (social marks, the sanity ceiling) rather than a
            second, drifting copy of it here.
        identifiers: the COLLAPSED creator identifiers for this post (`_creator_identifiers`).
        marks: the COLLAPSED brand marks this deck may not reprint (`mark_identifiers`).
        source_panel_count: the SOURCE deck's own panel count, for the coverage assertion.

    The ORDER is load-bearing and is not the order the plan lists the guards in:

    1. digits, 2. alignment, 5. truncation — the three that can RESTORE `source_text_original`,
    first, because each restores PRE-layer-3 bytes: the source panel with its creator header, its
    watermark and its commit line still on it. Running the identity scrub before them would scrub
    a string that is about to be thrown away and ship the un-scrubbed one in its place.
    3. dedupe — next, so it deduplicates whatever ended up shipping rather than whatever was
    shipping before a restore.
    4/9. identity and chrome — LAST, so every path out of this function, restored or original, has
    had every other party's name taken off it. That is the invariant worth having: no byte leaves
    here that names somebody else.

    Then the deck-level pass: duplicate positions (realigned, first claim wins) and the coverage
    assertion, which are questions about the SET of rows rather than about any one of them.
    """
    out: list[dict[str, Any]] = []
    tags: list[DegradationTag] = []
    warnings: list[GuardWarning] = []
    authored: list[str] = []
    dropped_refs: list[str] = []
    duplicates = set(duplicate_positions(rows))
    #: Every row's pre-gate source panel, in position order — guard 2's rival test reads the whole
    #: list, because "these words belong to a DIFFERENT row" is a question about the deck.
    originals = [str(row.get("source_text_original") or "") for row in rows]
    # Guard 9's vocabulary, minus the marks this deck is ABOUT (`subject_marks`): a mark written
    # into other panels' sentences is the deck's subject and its bare line is a legitimate slide.
    marks = set(marks) - subject_marks(rows, marks)
    # Per-guard slide ledgers: one aggregated warning per guard per creative, in the house style
    # (`panel_over_budget` and its siblings) — twelve slides is one line the operator reads, not
    # twelve lines they scroll past.
    repaired: list[str] = []
    drifted: list[str] = []
    realigned: list[str] = []
    deduped: list[str] = []
    truncated: list[str] = []
    scrubbed: list[str] = []
    chromed: list[str] = []
    for index, source_row in enumerate(rows):
        row = dict(source_row)
        # The one-row-schema contract (D54): both D65 keys are written on EVERY row of every walk,
        # false by default, so a reader never has to ask whether they exist.
        row.setdefault("identity_scrubbed", False)
        row.setdefault("chrome_watermark_stripped", False)
        slide = _int(row.get("slide")) or index + 1
        shipped = str(row.get("source_text") or "")
        original = str(row.get("source_text_original") or "")
        translated = bool(row.get("translated"))
        out.append(row)
        if not shipped.strip():
            continue  # a wordless row has no contract to guard — FR-304 already explained it
        before = shipped
        # True once a guard threw this row's words away wholesale — restored the source panel over
        # them, or left the slide wordless. Kept apart from "the text changed at all": a healed
        # `I6GB` or a collapsed duplicate line is still the compression / the translation the walk
        # produced, and wiping those receipts would tell meta.yaml the deck shipped a contract it
        # never shipped.
        replaced = False
        # --- guard 1: digits -------------------------------------------------------------
        digits = guard_digits(shipped, original)
        shipped = digits.text
        for token, healed in digits.repaired:
            repaired.append(f"slide {slide} ({token} -> {healed})")
        for token, source_token in digits.restored:
            drifted.append(f"slide {slide} ({token} -> {source_token})")
        if digits.row_replaced:
            drifted.append(f"slide {slide} (numbers the source panel never wrote)")
        if digits.drifted:
            tags.append(DegradationTag.COPY_DIGIT_DRIFT)
        if digits.row_replaced:
            shipped = _fallback(original, translated=translated, admits=admits)
            replaced = True
        # --- guard 2: row alignment ------------------------------------------------------
        # Skipped on a TRANSLATED row: its words are in a different language from the panel it
        # renders, so it shares no content words with its own original BY DESIGN and every
        # translated deck would realign itself back into its source language.
        mine = content_overlap(shipped, original) if shipped.strip() and original.strip() else 1.0
        rival, rival_score = ((0, 0.0) if translated or mine >= ALIGNMENT_FLOOR
                              else best_rival(shipped, originals, index))
        misaligned = index in duplicates or (
            not translated and mine < ALIGNMENT_FLOOR
            and rival_score >= _RIVAL_FLOOR and rival_score > mine)
        if misaligned:
            realigned.append(f"slide {slide} ("
                             + ("a second row claiming source panel "
                                f"{_int(row.get('source_position'))}" if index in duplicates
                                else f"overlap {mine:.2f} with its own panel, {rival_score:.2f} "
                                     f"with source panel {rival}") + ")")
            shipped = _fallback(original, translated=translated, admits=admits)
            replaced = True
            tags.append(DegradationTag.PANEL_MAP_REALIGNED)
        # --- guard 5: truncation ---------------------------------------------------------
        # TWO signals, and they do NOT get the same power, because they are not the same quality
        # of evidence:
        #
        # * `tail` is a cut this function can SEE in the bytes about to be rendered — an unclosed
        #   bracket, a trailing comma, a list marker with no item, a word cut in half. None of
        #   those is ever authored, so a row carrying one either restores its original or goes
        #   wordless. This is the audit's `( src/types/in` class.
        # * `suspect` is `ocr_repair.truncation_suspect`'s boolean, inherited from the SOURCE panel
        #   at admission. Its strongest arm (the mid-word cut) fires on any panel over 60
        #   characters that ends on a lower-case word with no full stop — which is how a great many
        #   perfectly finished carousel panels end. Given the power to blank, it would empty
        #   slides by the dozen, and a wordless slide beside a source slide full of words is the
        #   exact failure FR-304 exists to prevent. So it may RESTORE an un-cut original (the
        #   PRD's "ship the un-truncated original"), and where there is no better original to ship
        #   it leaves the words alone — FR-304c's pre-D65 behaviour, with the flag still riding to
        #   the critic, which can look at the frame and settle what a heuristic cannot.
        #
        # It is also read only on a row that ships the SOURCE's own bytes: on a compressed or
        # translated row the flag describes a panel whose words are not the ones on the slide.
        tail = truncated_tail(shipped)
        suspect = (bool(row.get("truncation_suspect"))
                   and not row.get("compressed") and not translated)
        if shipped.strip() and (tail or suspect):
            whole = _fallback(original, translated=translated, admits=admits)
            restored = (whole if whole.strip() and whole != shipped
                        and not truncated_tail(whole) else "")
            replacement = restored or ("" if tail else shipped)
            if replacement != shipped:
                truncated.append(f"slide {slide} ("
                                 + (f"ends on {tail!r}" if tail else "flagged at admission")
                                 + (", restored" if replacement.strip() else ", wordless") + ")")
                shipped = replacement
                replaced = True
        # --- guard 3: dedupe -------------------------------------------------------------
        shipped, repeats = dedupe_lines(shipped)
        if repeats:
            deduped.append(f"slide {slide} ({len(repeats)} repeated line(s): "
                           + "; ".join(sorted(set(repeats))[:3]) + ")")
        # --- guards 4 and 9: identity and chrome -----------------------------------------
        identity = scrub_identity(shipped, identifiers=identifiers, marks=marks)
        if identity.changed:
            shipped = "" if identity.beheaded else identity.text
            replaced = replaced or identity.beheaded
            row["identity_scrubbed"] = bool(identity.identity)
            row["chrome_watermark_stripped"] = bool(identity.chrome)
            if identity.identity:
                scrubbed.append(f"slide {slide} ({'; '.join(identity.identity[:2])}"
                                + (", row left wordless: what remained read as a fragment"
                                   if identity.beheaded else "") + ")")
            if identity.chrome:
                chromed.append(f"slide {slide} ({'; '.join(identity.chrome[:2])})")
        # --- commit the row --------------------------------------------------------------
        if shipped != before:
            row["source_text"] = shipped
            if replaced or not shipped.strip():
                # The words the walk produced are gone — restored from the source panel, or gone
                # entirely. A compressed row that ships its own original is not a compression, a
                # translated row that ships nothing is not a translation, and the ref label claims
                # a byte identity with the ADMITTED panel that neither of those has any more. A
                # wordless row's label is empty on every walk, so this is also just FR-304's own
                # rule applied by a later hand.
                if row.get("ref_label"):
                    dropped_refs.append(f"slide_{slide}")
                    row["ref_label"] = ""
                row["compressed"] = False
                row["translated"] = False
            if shipped.strip():
                authored.append(shipped)
    # --- guard 6: coverage ---------------------------------------------------------------
    if unmapped := unmapped_positions(out, source_panel_count):
        tags.append(DegradationTag.PANEL_DROPPED_UNMAPPED)
        warnings.append(GuardWarning(
            "panel_dropped_unmapped",
            f"{asset_id}: source panel(s) {unmapped} have NEITHER a panel_map row NOR a recorded "
            f"drop reason — the deck maps {len(out)} of the {_int(source_panel_count)} panel(s) "
            "this post carries and cannot say what became of the rest. Every position inside a "
            "deck's own length is meant to be accounted for, shipped or dropped, and a source "
            "panel that simply vanished is the one failure FR-304's row-is-the-alignment rule "
            "cannot absorb (FR-362). The creative still ships; what it may not do is ship "
            "silently", {"asset_id": asset_id, "positions": unmapped,
                         "rows": len(out), "source_panel_count": _int(source_panel_count)}))
    warnings.extend(_ledger_warnings(asset_id, repaired, drifted, realigned, deduped,
                                     truncated, scrubbed, chromed))
    return GuardedDeck(rows=tuple(out), texts=tuple(str(row.get("source_text") or "")
                                                    for row in out),
                       authored=tuple(authored), tags=tuple(dict.fromkeys(tags)),
                       warnings=tuple(warnings), dropped_refs=tuple(dropped_refs))


def guard_caption(caption: str, *, asset_id: str, identifiers: Iterable[str] = (),
                  marks: Iterable[str] = (), quoted: bool = True) -> GuardedCaption:
    """FR-363 — the caption's identity scrub and its voice hand-raise, in one pass.

    `quoted` says whether these words came from a SOURCE POST at all. On an override brief the
    caption is written from the operator's own directives, so "I" in it is the operator — the
    voice test would raise a hand at our own house style and teach the operator to ignore the
    tag. The identity scrub still runs on every caption whatever this says: a commit hash or
    somebody else's handle has no business in our caption however the caption was built.

    The scrub is guard 4's, unchanged and for the same reason: a caption that names the source
    creator, quotes their commit or reprints their watermark publishes their identity under our
    account. It is line-level like the deck's, so the ordinary single-paragraph caption is
    untouched by it.

    The VOICE test changes nothing at all. FR-331 keeps the caption verbatim and this raises a
    hand: the caption ships as written, the tag puts it on the console and the gallery card, and
    the operator decides whether our account is going to say "I quit my job" about somebody else's
    job.
    """
    caption = str(caption or "")
    tags: list[DegradationTag] = []
    warnings: list[GuardWarning] = []
    identity = scrub_identity(caption, identifiers=identifiers, marks=marks)
    scrubbed = identity.changed and not identity.beheaded
    if identity.changed:
        # A beheaded CAPTION keeps its bytes: a creative with no caption cannot be published at
        # all (`NoSafeCaptionError` is a run-stopping condition upstream), so the honest trade
        # here is the opposite of the deck's — the fragment ships and the warning names it.
        warnings.append(GuardWarning(
            "caption_identity_scrubbed",
            f"{asset_id}: the caption named another party and that line was removed — "
            + "; ".join((*identity.identity, *identity.chrome))
            + (". What remained reads as a fragment of the line that went, and it ships anyway: "
               "a creative with no caption cannot be published, so this one is the operator's to "
               "read" if identity.beheaded else ""),
            {"asset_id": asset_id, "lines": [*identity.identity, *identity.chrome]}))
        caption = caption if identity.beheaded else identity.text
    if quoted and caption_voice_suspect(caption):
        hits, total = first_person_starts(caption)
        tags.append(DegradationTag.CAPTION_VOICE_REVIEW)
        warnings.append(GuardWarning(
            "caption_voice_review",
            f"{asset_id}: {hits} of this caption's {total} sentence(s) open in the first person "
            "singular — it reads as the SOURCE creator's own voice, and published under our "
            "account it is their story told as ours. The caption ships VERBATIM regardless "
            "(FR-331: the engine does not rewrite a quote to sound like us); this is a hand "
            "raised for the operator, on the console and on the gallery card, and nothing else "
            "(FR-363)",
            {"asset_id": asset_id, "first_person_sentences": hits, "sentences": total,
             "caption": caption[:200]}))
    return GuardedCaption(caption=caption, tags=tuple(tags), warnings=tuple(warnings),
                          scrubbed=scrubbed)


def _fallback(original: str, *, translated: bool, admits: Callable[[str], bool]) -> str:
    """The bytes a row falls back to when a guard refuses what it was shipping.

    The source's own panel, if that panel may ship at all — `admits` is the copy stage's own
    FR-304 admission gate, so a fallback faces the same social-mark and sanity-ceiling tests the
    walk applied, never a second copy of them. Otherwise the empty string: FR-304's rule for every
    panel it cannot admit is a wordless slide in its own position, and a guard does not get a
    different rule.

    A TRANSLATED row never restores. Its `source_text_original` is the panel in the language the
    operator asked us to translate OUT of, and putting those bytes on the slide would answer a
    corrupted row with a foreign one — the deck would ship half in German under a receipt saying
    it is in English. Those rows go wordless instead, which is a loss of one slide's words rather
    than a loss of the deck's language.
    """
    if translated:
        return ""
    original = str(original or "")
    return original if original.strip() and admits(original) else ""


def _ledger_warnings(asset_id: str, repaired: Sequence[str], drifted: Sequence[str],
                     realigned: Sequence[str], deduped: Sequence[str], truncated: Sequence[str],
                     scrubbed: Sequence[str], chromed: Sequence[str]) -> list[GuardWarning]:
    """One warning per guard that fired, naming every slide it touched — never one per slide.

    The house shape (`panel_over_budget`, `panel_handle_or_url`, `panel_emptied_by_strip`): the
    operator reads a line per FINDING with the slides enumerated inside it, and the structured
    fields carry the full list for the log. Nothing is emitted for a guard that changed nothing,
    because a clean deck must be silent for a fired guard to be visible.
    """
    out: list[GuardWarning] = []
    if repaired:
        out.append(GuardWarning(
            "panel_digits_repaired",
            f"{asset_id}: {len(repaired)} numeric token(s) on this deck were OCR misreadings of "
            f"their own source panel's digits and were healed — {'; '.join(repaired)}. This is a "
            "repair, not a loss: the letters `I`, `l`, `O` and `o` were standing where the source "
            "panel has digits, and the corrected bytes are the source's own (FR-362)",
            {"asset_id": asset_id, "tokens": list(repaired)}))
    if drifted:
        out.append(GuardWarning(
            "copy_digit_drift",
            f"{asset_id}: {len(drifted)} numeric token(s) disagreed with the same row's "
            f"source_text_original beyond an OCR misreading — {'; '.join(drifted)}. The SOURCE's "
            "bytes ship in their place (the whole panel where the token structure differs too far "
            "to do surgery): a number on a slide is a claim about the world, and a claim the "
            "source never made is the one thing the verbatim contract exists to prevent (FR-362)",
            {"asset_id": asset_id, "tokens": list(drifted)}))
    if realigned:
        out.append(GuardWarning(
            "panel_map_realigned",
            f"{asset_id}: {len(realigned)} row(s) shared almost no words with their OWN source "
            f"panel — {'; '.join(realigned)} — which is what a deck whose rows slipped by one "
            "position looks like from the inside. Each ships the verbatim original instead, or "
            "renders wordless in its own position where the original cannot be admitted; nothing "
            "is re-ordered, because the row IS the alignment (FR-362)",
            {"asset_id": asset_id, "slides": list(realigned)}))
    if deduped:
        out.append(GuardWarning(
            "panel_lines_deduped",
            f"{asset_id}: {len(deduped)} row(s) repeated a line inside themselves and the repeat "
            f"was collapsed — {'; '.join(deduped)}. A duplicated OCR line is an ORDER to print it "
            "twice, and the post-render critics then fail the frame for printing it once "
            "(FR-362)", {"asset_id": asset_id, "slides": list(deduped)}))
    if truncated:
        out.append(GuardWarning(
            "panel_truncation_gated",
            f"{asset_id}: {len(truncated)} row(s) read as CUT rather than finished — "
            f"{'; '.join(truncated)}. Each ships its un-truncated source panel instead, or "
            "nothing "
            "at all when that panel is cut too. D65 turns FR-304c's flag into a gate: a slide "
            "whose sentence stops mid-air is not a slide, and the operator would rather have a "
            "wordless frame than a public one that ends on an open bracket (FR-362)",
            {"asset_id": asset_id, "slides": list(truncated)}))
    if scrubbed:
        out.append(GuardWarning(
            "panel_identity_scrubbed",
            f"{asset_id}: {len(scrubbed)} row(s) carried another party's identity — a creator "
            f"handle, a commit line, a repository or issue reference — {'; '.join(scrubbed)}. The "
            "line is removed WHOLE rather than edited: an order to render somebody else's name is "
            "an order the renderer obeys, and a sentence with the name cut out of its middle is a "
            "sentence nobody wrote (FR-362)",
            {"asset_id": asset_id, "slides": list(scrubbed)}))
    if chromed:
        out.append(GuardWarning(
            "panel_watermark_stripped",
            f"{asset_id}: {len(chromed)} row(s) were a source brand mark or watermark reprinted "
            f"as our own words — {'; '.join(chromed)}. Stripped into chrome exactly as a page "
            "counter is, and kept in source_text_original: a watermark promoted to a headline is "
            "how run 4344 shipped `EVOLVING A` as a hero line and then CHOSE that cover, because "
            "the cover picker was reading the same corrupted contract (FR-362)",
            {"asset_id": asset_id, "slides": list(chromed)}))
    return out


def _int(value: Any) -> int:
    """A non-negative int from anything a row can hold — the copy stage's own coercion."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


__all__ = ["ALIGNMENT_FLOOR", "DigitFinding", "GuardWarning", "GuardedCaption", "GuardedDeck",
           "IdentityFinding", "beheaded", "best_rival", "caption_voice_suspect", "content_overlap",
           "content_words", "dedupe_lines", "digits_of", "duplicate_positions",
           "first_person_starts", "guard_caption", "guard_deck", "guard_digits",
           "mark_identifiers", "numeric_tokens", "repair_token", "scrub_identity",
           "strip_lines_equal", "subject_marks", "token_drifted", "truncated_tail",
           "unmapped_positions"]
