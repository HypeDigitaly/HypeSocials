"""MARK NAMES — one spelling of a brand mark, however the vision pass wrote it down.

Module contract
---------------
Purpose: turn the free-form string a vision pass produces for a logo it saw (`"Claude
logo/wordmark, top left"`) into the two normalized forms the rest of the pipeline joins on — the
BRAND NAME (`"Claude"`) and its COLLAPSED identity key (`"claude"`). Nothing else: no sanctioning,
no chrome test, no cropping, no I/O.

Public API: `mark_name(raw) -> str` · `collapse(text) -> str`.

Why it lives in `sources/` (v2.2.0). Both functions were private to `generate/carousel.py`, and by
the 08-14 audit three more call sites wanted them: `sources/logo_crops.py` needs the collapsed key
to dedupe crops and to test a box against the sanctioned allowlist, `sources/slide_intel.py` needs
it to drop the author's own identity out of `_mark_boxes`, and the deck itself needs it to join a
patch onto the slide that sanctioned it. `logo_crops.py:112` collapsing the RAW name while
`carousel.py:429` collapsed the PEELED name is precisely the drift a shared module ends: two
spellings of the same mark, no join, no patch, a recoloured logo on a paid slide.

`sources` is the right home rather than a new top-level module because the strings these functions
normalize come FROM this domain — they are what `slide_intel` transcribed off a source slide — and
because the import direction `sources <- generate` already exists (`generate` imports `sources`,
never the reverse), so hosting them here creates no cycle.

Both functions are TOTAL and pure: any input, including `None` and non-strings, produces a string.
A mark whose brand could not be named reduces to `""`, which every caller reads as "never
sanction this" — the right answer for a mark the vision pass only described.
"""

from __future__ import annotations

import re

#: The descriptors a vision pass appends when it names what it saw ("Notion logo icon"). They
#: describe the ENTRY, not the brand, and a render model given them draws the word.
_MARK_DESCRIPTORS = ("logo", "logos", "icon", "icons", "wordmark", "mark", "marks", "badge",
                     "glyph", "symbol", "app", "lockup",
                     # shape words a vision pass uses for a glyph it recognizes ("Claude
                     # asterisk icon", 59el deck 06) — descriptors of the mark, never the brand
                     "asterisk", "sunburst", "emblem")
#: The characters a vision pass uses to staple two descriptors onto one word ("logo/wordmark",
#: "logo+wordmark", "logo & wordmark"). Split as separators AND kept, so `mark_name` can peel the
#: pieces and then rebuild whatever survived exactly as it was written.
_JOINER = re.compile(r"([/+&])")


def mark_name(raw: str) -> str:
    """`"Notion logo icon"` -> `"Notion"` — the brand, without the words that described the entry.

    Trailing descriptors are peeled one at a time, so "app icon" and "logo mark" both reduce; a
    string that is ONLY descriptors ("logo") reduces to nothing and is therefore never sanctioned,
    which is the right answer for a mark whose brand the vision pass could not name.

    JOINED descriptors peel too (v2.1.4). A vision pass writes "Claude logo/wordmark" as readily
    as "Claude logo", and to a peeler that splits on whitespace `logo/wordmark` is one unknown
    word: the peel stopped dead, the name stayed `"Claude logo/wordmark"`, and the join onto the
    patch table (keyed `claude`) missed. In the glz0 run that cost deck 06 the Claude patch it had
    already cropped and uploaded — `mark_patches_attached patched: []` — and the cover recoloured
    the Claude mark into the style's teal, which is the exact defect FR-315 was built to end. So
    `/`, `+` and `&` are treated as word breaks WHILE peeling.

    They are not, however, rewritten. Each word is exploded on its joiners, the descriptor tail is
    peeled off the pieces, and whatever survives is rebuilt with its ORIGINAL joiner — so
    "AT&T logo" reduces to "AT&T" and never to "AT T". A brand whose name contains an ampersand
    is a brand, not a list.

    Idempotent: `mark_name(mark_name(x)) == mark_name(x)`, which is what lets a caller apply it to
    a name that may already be peeled (a sanctioned entry) and to one that certainly is not (a raw
    box label) and still get one key out of both.
    """
    # A trailing comma-clause is a LOCATION, not a name: the vision pass writes "Claude
    # logo/wordmark, top left" and "Claude asterisk icon, inside Decision Brief banner". The
    # 59el run proved the peeler cannot exhaust free-form location prose ("top", "left",
    # "banner"…), so everything after the first comma is cut before peeling begins — a brand
    # name containing a comma is not a thing the registry or the vision pass produces.
    raw = str(raw or "").split(",", 1)[0]
    pieces: list[tuple[str, str]] = []  # (joiner that PRECEDES this piece, piece)
    for index, word in enumerate(raw.replace("(", " ").replace(")", " ").split()):
        parts = _JOINER.split(word)  # ['logo', '/', 'wordmark'] — separators kept
        pieces.append((" " if index else "", parts[0]))
        pieces.extend(zip(parts[1::2], parts[2::2]))
    while pieces and (not (tail := pieces[-1][1].strip(".,:;'\""))
                      or tail.casefold() in _MARK_DESCRIPTORS):
        pieces.pop()  # an empty piece is a dangling joiner ("Claude logo / wordmark"), not a name
    return "".join(joiner + piece for joiner, piece in pieces).strip(" -–—,:;\"'/+&")


def collapse(text: str) -> str:
    """`"@The Roman Knox"` -> `"theromanknox"` — one identity, however it was typed.

    A creator's mark is transcribed as an @handle on one slide and as a spaced account name on the
    next, so the author test has to compare the two with the punctuation and spacing gone. Accents
    are KEPT (`casefold` only): "Rychlejší" and "Rychlejsi" are different words in a Czech deck,
    and folding them together would strip lines nobody asked to strip.

    Collapsing a RAW box label and collapsing its PEELED name give different keys, so a caller
    joining two sides of the same mark must apply `mark_name` to BOTH before collapsing — that
    asymmetry is the defect this module was extracted to make impossible to re-introduce quietly.
    """
    return "".join(char for char in str(text or "").casefold() if char.isalnum())


__all__ = ["collapse", "mark_name"]
