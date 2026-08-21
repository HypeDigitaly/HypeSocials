"""OCR REPAIR — the ONE sanctioned mutation on the verbatim path, and its two guard rails.

Module contract
---------------
Purpose: repair the small class of transcription confusables that a vision pass reliably produces
(`Al` for `AI`, `0` for `O` inside an uppercase token) and flag text that looks like it was CUT
rather than written. Nothing else: no normalization, no case folding, no punctuation tidying, no
translation, no trimming.

Public API: `repair_confusables(text) -> (text, [Correction])` · `truncation_suspect(text) -> bool`.

Doctrine (FR-100/FR-101 as amended v2.2.0, and the reason this module is this small)
-----------------------------------------------------------------------------------
The pipeline's central promise is that every string that becomes pixels is a byte-substring of a
source post (FR-100's verifier). A repair is therefore not a cosmetic nicety — it MOVES the bytes
the verifier compares against, and a repair applied in one place but not another turns a correct
deck into a `copy_not_verbatim` failure. So:

1. **One boundary.** Repair is applied at the SANCTIONED ADMISSION BOUNDARY only — the moment a
   candidate string is admitted into the run (caption/hook admission, the merged panel payload,
   `slide_intel`'s `vision_text`). The SAME repaired bytes must then feed the verifier's candidate
   pool, the prompt payload, and `panel_map.source_text`. Never repair downstream, never repair
   twice, never repair on one of those three paths alone.
2. **Raw bytes always survive.** `panel_map.source_text_original` keeps the unrepaired string, and
   every correction is logged (`ocr_repaired`). A repair that cannot be pointed at afterwards is
   indistinguishable from the drift this whole design exists to prevent.
3. **A truncation suspect is FLAGGED, NEVER BLANKED — by THIS module.** `truncation_suspect`
   returns a boolean and this module offers no function that shortens, completes or discards text.
   A panel ending in "…" is CONTENT — the source author wrote it that way as often as an OCR pass
   cut it — and this module has no way to tell the two apart.

   *(Amended v2.9.0, D65/FR-362.)* What a CALLER may do with the flag has changed, and this note is
   here so the two files do not read as contradicting each other. `contract_guard`'s guard 5 now
   treats the flag as a GATE rather than a note: a flagged row ships its un-truncated
   `source_text_original` instead, or renders wordless in its own position when that original is
   cut too. The reason the old rule gave for never blanking — "dropping the panel would silently
   re-map the whole deck" — is answered rather than overruled: the guard never drops a ROW, only
   its words, so FR-304's alignment is untouched and the operator gets a wordless frame instead of
   a public one whose sentence stops mid-air (the audit's `( src/types/in` class). This module's
   own contract is unchanged: it still only ever returns a boolean.
4. **Uppercase-token scope.** Every substitution here is confined to tokens that are wholly
   upper-case (plus the `Al`→`AI` title-case case, which is the specific defect measured). Applied
   to ordinary prose, `l`→`I` and `0`→`O` would rewrite half of every Czech and English caption
   the pipeline quotes. The narrowness IS the safety property, not a limitation to be relaxed
   later; widening this set needs the FR-100 verifier re-examined in the same change.

Pure and total: no I/O, no config, no logging of its own (callers log what they applied), and any
input including `None` yields a string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: A word-ish token: letters, digits and the intra-word punctuation a brand or acronym carries.
#: Split with the separators KEPT, so a repaired string can be rebuilt with its original spacing
#: byte for byte — the whole module is worthless if reassembly is lossy.
_TOKEN = re.compile(r"([^\W_]+)", re.UNICODE)

#: Whole tokens a vision pass mis-transcribes as a unit, mapped to what they must have been. Keyed
#: EXACTLY as written, because the mistake is the shape of the whole word and not any one of its
#: letters. `"Al"` is the measured case — a capital I read as a lowercase L, which arrives as "Al
#: agents", "Al tools", "5 Al workflows" — and it is also a real given name (Al Pacino, Al Gore),
#: so it is repaired only in the position where the name reading is impossible: see `_repair_token`.
_WHOLE_TOKEN: dict[str, str] = {"Al": "AI", "AL": "AI"}

#: Per-character repairs applied INSIDE an already-uppercase token only (rule 4 above). The digit
#: forms are the common direction — a vision pass reads `0` for `O` and `1` for `I` far more often
#: than the reverse — and `l` is the lowercase-L that survives inside an otherwise upper-case run.
_IN_UPPER: dict[str, str] = {"0": "O", "1": "I", "5": "S", "l": "I", "|": "I"}

#: An upper-case token shorter than this is not evidence of anything: "A0" is as likely a model
#: number as a defect, and repairing it invents a word. Three characters is where an all-caps run
#: stops being ambiguous.
_MIN_UPPER_TOKEN = 3

#: Tokens that are legitimately mixed digits and capitals — repairing them would break the very
#: strings they name. Extended by measurement, never by guess. This list names PRODUCTS; the
#: measurement shapes it used to have to name one at a time are `_MEASUREMENT` below.
_NEVER_REPAIR = frozenset({"H2O", "MP3", "MP4", "GPT4", "GPT5", "CO2", "B2B", "B2C", "K2", "P2P"})

#: The unit suffixes that turn a leading digit run into a MEASUREMENT rather than an acronym.
#: A closed, small vocabulary on purpose: units are a stable set, product names are not, and the
#: allowlist above was losing a race it could never win (it named `MP3` and `GPT5` and still let
#: `16GB` through). Order does not matter; the match is exact against the token's letter tail.
_UNITS = frozenset({
    "B", "K", "M", "X", "KB", "MB", "GB", "TB", "PB", "KW", "MW", "HZ", "KHZ", "MHZ", "GHZ",
    "FPS", "PX", "PT", "MS", "S", "H", "D", "W", "Y", "BPS", "KBPS", "MBPS", "GBPS", "RPM", "DPI"})

#: A leading run of digits followed by a unit — `16GB`, `146K`, `10X`, `70B`, `128GB`, `500MS`.
_MEASUREMENT = re.compile(r"^\d+([A-Z]+)$")

#: `truncation_suspect`: the ellipsis forms an OCR pass and a source author both produce. Their
#: presence is a SUSPICION and never a verdict — see doctrine point 3.
_ELLIPSIS = ("…", "...", "..")

#: A word left hanging on its own hyphen ("develop-") is the least ambiguous cut there is: no
#: author ends a panel that way, and a container that clipped one does it constantly.
_HANGING = ("-", "‑", "–", "—")

#: The mid-word-cut heuristic's three conjunct conditions, kept narrow on purpose. A panel ending
#: without punctuation is COMPLETELY NORMAL — most headlines and most panel lines do — so a bare
#: "no full stop" test would flag the majority of every deck and the flag would mean nothing. The
#: signal is only worth reading when the line is long enough to have plausibly hit a limit AND its
#: final token is a lower-case word still in flight (not a name, not an acronym, not a number,
#: which are all things a finished line legitimately ends on).
_MIN_CUT_LENGTH = 60
_MIN_CUT_TOKEN = 4
#: Anything here at the end of a line means the line ENDED. Includes closing brackets and quotes,
#: which are how a finished parenthetical or quotation stops. Dashes are absent deliberately —
#: `_HANGING` has already claimed them, in the opposite direction.
_TERMINALS = ".!?:;,)]}\"'»”’…/\\|*#"


@dataclass(frozen=True, slots=True)
class Correction:
    """One applied repair, in the shape a log line and an operator both need.

    `index` is the character offset of `before` in the ORIGINAL text, so a caller can point at the
    exact site in `source_text_original` rather than asking a reader to diff two strings.
    """

    before: str
    after: str
    index: int


def repair_confusables(text: str) -> tuple[str, list[Correction]]:
    """Repair uppercase-scoped OCR confusables; return the repaired text and what was changed.

    Two passes, both word-boundary scoped and neither able to change a string's length in a way
    that shifts anything around it:

    1. **Whole-token swaps** (`_WHOLE_TOKEN`) — a token that IS the mistake. This is the `Al`→`AI`
       class, the defect actually measured in the 08-14 audit: source panels reading "Al agents"
       where the slide said "AI agents", carried verbatim into paid pixels. Guarded by one
       look-ahead so a person's given name survives (see `_repair_token`).
    2. **In-token character swaps** (`_IN_UPPER`) — applied ONLY inside a token that is already
       upper-case, at least `_MIN_UPPER_TOKEN` long, not in `_NEVER_REPAIR`, and that contains at
       least one real letter (so "2024" and "100" are never touched).

    Returns `(text, [])` unchanged whenever nothing matched — callers can treat an empty list as
    "these are the original bytes" and skip writing `source_text_original` at all.

    Deliberately NOT here: sentence casing, whitespace collapsing, quote straightening, dash
    normalization, accent folding. Each is a mutation the verifier would have to be taught about,
    and each would silently change what a Czech or an emoji-carrying source panel renders as. This
    function is the sanctioned exception; it is not a place to add more of them.
    """
    original = str(text or "")
    if not original:
        return "", []
    tokens = _TOKEN.split(original)  # words at the ODD indices, separator runs at the even ones
    corrections: list[Correction] = []
    offset = 0
    for position, piece in enumerate(tokens):
        if position % 2 == 0:  # a separator run — never touched
            offset += len(piece)
            continue
        following = tokens[position + 2] if position + 2 < len(tokens) else ""
        fixed = _repair_token(piece, following=following)
        if fixed != piece:
            corrections.append(Correction(before=piece, after=fixed, index=offset))
            tokens[position] = fixed
        offset += len(piece)
    return ("".join(tokens), corrections) if corrections else (original, [])


def _repair_token(token: str, *, following: str) -> str:
    """One token, repaired or returned unchanged. See `repair_confusables` for the two passes.

    `following` is the next WORD in the string (`""` at the end) and exists for exactly one
    judgement: `"Al"` is the confusable when what comes after it is a lower-case word or nothing
    ("Al agents", "5 Al tools", "…s Al"), and is a person's given name when what comes after it is
    capitalised ("Al Pacino", "Al Gore"). That one look-ahead is the whole difference between
    repairing the defect the audit measured and rewriting somebody's name on a published slide.
    """
    if token in _NEVER_REPAIR:
        return token
    if (swapped := _WHOLE_TOKEN.get(token)) is not None:
        return token if following[:1].isupper() else swapped
    if len(token) < _MIN_UPPER_TOKEN or not _is_acronym(token):
        return token
    return "".join(_IN_UPPER.get(char, char) for char in token)


def _is_acronym(token: str) -> bool:
    """An ALL-CAPS run with at least one letter — the only scope a character swap is safe in.

    `token.isupper()` alone is false for "AI2" in some scripts and true for "2024" in none, so the
    letter test is explicit: a token of pure digits is a number, not an acronym, and repairing
    "2024" into "ZOZ4" is the failure mode this guard exists for.

    **A MEASUREMENT is not an acronym (D65).** `16GB`, `146K`, `10X`, `70B` and `128GB` are all-caps
    runs containing letters, so every one of them used to reach the character swap and come out as
    `I6GB`, `I46K`, `IOX`, `7OB`, `I28GB` — this module MANUFACTURING the exact corruption the
    2026-08-21 audit found rendered onto published slides, which FR-362's guard 1 then spent its
    life undoing off `source_text_original`. The discriminator is the token's shape rather than its
    spelling: a run of digits followed by a known UNIT is a quantity, and its digits are the
    content. `_NEVER_REPAIR` cannot do this job — it names products one at a time and a unit
    vocabulary is closed where a product vocabulary is not. A digit-led token whose tail is NOT a
    unit (`0PENAI`) is still exactly the mis-read this repair exists for, and still repairs.
    """
    if (measurement := _MEASUREMENT.match(token)) and measurement.group(1) in _UNITS:
        return False
    return any(char.isalpha() for char in token) and token == token.upper()


def truncation_suspect(text: str) -> bool:
    """True when this string looks CUT rather than finished — a flag, never a licence to blank it.

    Three signals, all deliberately weak, and narrow by design — a flag that fires on half of
    every deck tells the critic nothing:

    - **Trailing ellipsis.** "…" or "..." at the end. A source author writing a cliff-hanger panel
      produces exactly this, so on its own it means only "look here".
    - **Hanging hyphen.** The line ends on "develop-". The least ambiguous of the three.
    - **Mid-word cut.** All three at once: the line is at least `_MIN_CUT_LENGTH` characters (long
      enough to have plausibly met a limit), it ends on no terminal punctuation at all, and its
      last token is a lower-case word of at least `_MIN_CUT_TOKEN` characters — still in flight,
      rather than the name, acronym or number a finished line ends on. Ending without a full stop
      is by itself completely ordinary and is NOT evidence.

    What a caller may do with `True`: set `panel_map.truncation_suspect` and hand it to the
    gauntlet's `brief` critic as contract data (FR-304c), which is looking at the rendered frame
    and can tell an authored ellipsis from a clipped container. What a caller may NEVER do: blank
    the panel, shorten it, drop its slide, or refuse it as a candidate. The panel keeps its
    position and its bytes — FR-304's alignment is the contract, and a heuristic does not get to
    break it.
    """
    stripped = str(text or "").rstrip()
    if not stripped:
        return False
    if stripped.endswith(_ELLIPSIS) or stripped.endswith(_HANGING):
        return True
    if len(stripped) < _MIN_CUT_LENGTH or stripped[-1] in _TERMINALS or not stripped[-1].isalnum():
        return False
    last = _TOKEN.findall(stripped)
    return bool(last) and len(last[-1]) >= _MIN_CUT_TOKEN and last[-1].islower()


__all__ = ["Correction", "repair_confusables", "truncation_suspect"]
