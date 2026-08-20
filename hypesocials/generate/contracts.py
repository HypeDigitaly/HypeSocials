"""What a frame was ORDERED to be — the gauntlet's referent, built once for all three call sites.

Module contract
---------------
Purpose: turn the things a creative already knows — its assigned meta-style, its verbatim text, its
sanctioned marks, its bound post, its competitor list — into the frozen `gauntlet.DeckContract` /
`gauntlet.FrameContract` pair the critics judge against (spec §1, FR-322/FR-330). Nothing else.

Public API: `frame_contract(...)` · `deck_contract(...)` · `panel_facts(env, entry)` ·
`gate_on(env)` · `forbidden_terms(...)`.

It exists as its own module rather than as three private helpers because the carousel, the
standalone image and the reel seed frame all need the SAME contract, and three copies of "what did
we order" would drift into three different verdicts about the same style. It is also the reason a
critic never sees a render prompt: everything here is contract DATA, assembled from the values the
prompt was built from, and the two style blocks that unavoidably ARE prompt text
(`style_dna`/`layout_zones`) are read through `prompts_engine`'s own public functions so they are
byte-identical to what the render model was told (FR-322's stated caveat, kept honest).

Invariants:
- **The words are verbatim and in order.** `body_lines` is the frame's own text split on its own
  line breaks, nothing trimmed, nothing normalised, nothing translated. An empty list is the strong
  claim "this frame is wordless BY MANDATE", which is the one thing a picture cannot tell a critic.
- **Wordless has a REASON.** `copywrite`'s `drop_reason` vocabulary is mapped onto spec §1's, so a
  bare frame says whether its source panel was empty, over the sanity ceiling, or a handle/URL.
- **The forbidden list is the expensive one (FR-330).** Competitor names, the source creator's own
  identity in every spelling that exists, and every brand mark the D-A sanction gate REFUSED. A
  name that is both sanctioned and forbidden is dropped from the forbidden side — the sanction gate
  is the authority, and telling a critic to fail a logo we deliberately ordered would spend the
  whole re-render budget undoing FR-315.

Do not: import `gauntlet`'s loop, price anything, call a model, or invent a style field — a value
that is not on `MetaStyle` is derived from its prose here, once, and said to be a derivation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from hypesocials.gauntlet import DeckContract, FrameContract
from hypesocials.models import MetaStyle, PlanEntry, VisionCheckResult
from hypesocials.prompts_engine import list_mode_text, style_dna, style_zones
from hypesocials.styles import is_list_panel

#: `copywrite`'s `panel_map.drop_reason` vocabulary -> spec §1's `wordless_reason`. Two spellings
#: exist because the two live at opposite ends of the run: one is the copy stage's record of why a
#: panel yielded no words, the other is the frozen enum the critic prompts name out loud. Mapped
#: rather than renamed — `meta.yaml`'s provenance rows are an operator-facing document (FR-73) and
#: re-spelling their values to suit a downstream consumer would rewrite history to fit its reader.
_WORDLESS_REASON: dict[str, str] = {
    "empty": "empty_panel",
    "over_budget": "over_sanity_ceiling",
    "contains_handle_or_url": "handle_or_url",
}

#: Sentence boundaries in authored style prose. The registry is hand-written English, so a full
#: stop, question mark or exclamation mark followed by whitespace is the whole grammar needed.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
#: What a style says when it renders something DELIBERATELY unreadable. There is no `MetaStyle`
#: field for it (spec §1 calls the value "derived from style"), and there should not be: the rule
#: lives in the author's own prose — "greeked bars", "texture lettering", "placeholder rows" — and a
#: separate field would be a second place to forget it. So the sentences that say so are lifted
#: whole, in the author's words. Without this a critic reads a style's own signature as `garbled`
#: (craft) or `invented_text` (brief) and blocks a deck for looking exactly as designed.
_ILLEGIBLE_WORDS: tuple[str, ...] = (
    "greek", "greeked", "greeking", "lorem", "placeholder text", "placeholder copy",
    "unreadable", "illegible", "unread", "texture lettering", "dummy text", "blurred text",
    "indistinct text", "non-text glyph", "nontext glyph", "abstract lettering",
)
#: A style's prose can run long; the critic needs the rule, not the essay.
_ILLEGIBLE_MAX = 600
#: One forbidden term is a NAME or a handle, never a sentence, and there is a limit to how many a
#: critic can hold in view at once. Both caps are this module's own belt against a malformed
#: upstream list turning one critic call into a page of strings.
_TERM_MAX = 60
_MAX_TERMS = 40
_MAX_MARKS = 8


def gate_on(env: Any) -> bool:
    """Is the post-render gate live for this run? (spec §4's `enabled`, plus a metered call.)

    Both halves are required and they fail for different reasons: `run.gauntlet.enabled: false` is
    the operator's rollback knob (NO gate — renders ship exactly as Kie returned them), and a
    missing `llm_call` is a preview or a unit test with no metered seam wired at all. Read through
    `getattr` because every consumer here targets the duck-typed `Env` surface, not its dataclass.
    """
    gauntlet = getattr(getattr(getattr(env, "config", None), "run", None), "gauntlet", None)
    return bool(getattr(gauntlet, "enabled", False)) and getattr(env, "llm_call", None) is not None


def panel_facts(env: Any, entry: PlanEntry) -> dict[int, dict[str, Any]]:
    """FR-304's `panel_map` rows, keyed by OUR slide number — `{slide: {reason, truncated}}`.

    The copy stage already recorded, per slide, whether its source panel yielded words and whether
    the words it did yield look cut off upstream (FR-304c). Both are contract facts the picture
    cannot supply: a frame that is bare because its panel was empty and a frame that is bare because
    its words failed to render are the same picture and opposite verdicts, and a string ending in an
    ellipsis is CONTENT on a truncation-suspect panel and a `truncated` defect anywhere else.

    Empty for an override brief, an unbound creative or a run whose `Env` carries no provenance —
    every consumer then reads the default row, which claims nothing.
    """
    prov = getattr(env, "copy_provenance", {}).get(entry.asset_id)
    rows = getattr(prov, "panel_map", ()) or () if prov is not None else ()
    facts: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            slide = int(row.get("slide") or 0)
        except (TypeError, ValueError):
            continue
        if slide > 0:
            facts[slide] = {
                "wordless_reason": _WORDLESS_REASON.get(str(row.get("drop_reason") or ""), ""),
                "truncation_suspect": bool(row.get("truncation_suspect")),
            }
    return facts


def frame_contract(
    number: int,
    text: str,
    *,
    style: MetaStyle | None = None,
    counter: str = "",
    signature: str = "",
    wordless_reason: str = "",
    truncation_suspect: bool = False,
) -> FrameContract:
    """ONE frame's row: the verbatim lines it was ordered to carry, and the four facts about them.

    `text` is the exact string the TEXT block locked — a mapped panel (FR-304), a composed slide
    line, an image headline+subline pair, a reel's overlay hook. It is split on its own line breaks
    and nothing else: blank lines are dropped because they are typography rather than content, and
    every surviving line travels byte for byte, in order, as `L1:`/`L2:`… in the critic's expected
    block. Nothing is trimmed here — a shortened quote is the defect the whole gate exists to catch.

    `is_list` is asked of the STYLE, through `styles.is_list_panel` — the same predicate that
    decided whether this frame's render prompt carried the list treatment (FR-304b/FR-329), so a
    critic can never be told to check pair integrity on a frame that was never set as a list.
    """
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    return FrameContract(
        number=number,
        body_lines=lines,
        # A frame with words cannot be wordless, whatever an upstream row says: `drop_reason` and
        # the shipped text are written at different moments, and the bytes that reached the prompt
        # are the ones the picture was ordered from.
        wordless_reason="" if lines else wordless_reason,
        truncation_suspect=bool(truncation_suspect),
        counter=str(counter or ""),
        signature=str(signature or ""),
        is_list=bool(style is not None and is_list_panel(style, str(text or ""))),
    )


def forbidden_terms(
    *,
    competitors: Iterable[str] = (),
    creator_forms: Iterable[str] = (),
    unsanctioned_marks: Iterable[str] = (),
    sanctioned: Iterable[str] = (),
) -> list[str]:
    """FR-330's FORBIDDEN side: everything whose PRESENCE on a frame is a leakage defect.

    Three independent sources, deduped case-insensitively and in a stable order (competitors first,
    because they are the list the operator configured and the one they will look for):

    * configured competitors plus this topic's guarded LLM strips (M6/§1.5);
    * the source creator's own identity, in every spelling the payload offers — a handle and a
      display name are transcribed interchangeably, and a critic looking for one will not see the
      other (FR-312);
    * every brand mark the D-A sanction gate REFUSED for this creative. A mark that is on the
      sanctioned list is removed from this one whatever else named it: the sanction gate is the
      authority (FR-315), and telling a critic to fail a logo we paid to render faithfully would
      spend the whole re-render budget undoing it.
    """
    allowed = {term.casefold() for term in (str(name).strip() for name in sanctioned) if term}
    out: list[str] = []
    seen: set[str] = set()
    for name in (*competitors, *creator_forms, *unsanctioned_marks):
        term = " ".join(str(name).split())[:_TERM_MAX]
        key = term.casefold()
        if term and key not in seen and key not in allowed:
            seen.add(key)
            out.append(term)
    return out[:_MAX_TERMS]


def creator_forms(post: Any) -> list[str]:
    """Every spelling of the source creator's identity this payload offers (FR-312/FR-316).

    Handle and display name both, raw as they arrived: the critic is reading PIXELS and matching
    what it reads against these strings, so a collapsed key ("emirailab") would be the one form that
    never appears on a slide. `sources.slide_intel` collapses the same two values for its own
    box-filtering; this is the human-readable half of the same fact.
    """
    return [form for form in (str(getattr(post, "author", "") or "").strip(),
                              str(getattr(post, "author_name", "") or "").strip()) if form]


def deck_contract(
    frames: Sequence[FrameContract],
    *,
    entry: PlanEntry,
    style: MetaStyle | None,
    wordmark: str = "",
    counter: str = "",
    required_marks: Iterable[str] = (),
    forbidden: Iterable[str] = (),
) -> DeckContract:
    """The deck-wide half of the referent: marks, forbidden strings, the style, the platform.

    `wordmark` and `counter` gate the style's own zone list exactly as the render prompt gated it
    (`prompts_engine.style_zones`), so `layout_zones` reads to the `system` critic as the layout the
    frames were actually ordered into — including the absence lines for a zone this creative did not
    fill. Passing the deck's values rather than a frame's is deliberate: `layout_zones` is
    deck-level in the frozen contract, and slide 1's signature is the deck's signature.

    **The honest caveat, for a CAROUSEL (D59/FR-338):** "exactly as the render prompt gated it" was
    never quite true for a deck's slides, because `carousel_slide.md` names no `{{layout_zones}}`
    slot — the frames were judged against a zone list no slide renderer was ever shown. Since D59
    one line of it does reach them, the `counter_slot` zone, through `prompts_engine.counter_rule`
    and the `_zone_line` formatter this value shares — so the badge, at least, is judged in the
    words it was ordered in. The rest of the list still reaches a slide only as `style_dna` prose,
    which is why `critic_system.md` may not fail a carousel frame for a zone that reached no render
    channel. On an image or a reel every zone here was in the prompt verbatim.

    `required_marks` is the union of what the D-A sanction gate allowed across the frames being
    judged (FR-315/FR-330's REQUIRED side); `forbidden` comes from `forbidden_terms()` above.
    """
    return DeckContract(
        frames=list(frames),
        required_marks=[str(name).strip()[:_TERM_MAX]
                        for name in required_marks if str(name).strip()][:_MAX_MARKS],
        forbidden_terms=list(forbidden),
        style_dna=style_dna(style),
        layout_zones=style_zones(style, wordmark=wordmark, slide_counter=counter),
        list_mode=list_mode_text(style),
        sanctioned_illegible=sanctioned_illegible(style),
        platform=str(entry.platform or ""),
    )


def sanctioned_illegible(style: MetaStyle | None) -> str:
    """What this style DELIBERATELY renders unreadable, in the style author's own words.

    Derived rather than declared (spec §1): the rule already exists in the registry as prose — a
    greeked mock-up bar, a texture of lettering, a placeholder row — and adding a field for it would
    create a second place to state the same thing and a first place to forget it. Every sentence of
    the style's `render_prompt`, its per-format guidance and its `exclusions` that names deliberate
    illegibility is lifted whole, deduped, in declaration order, and capped.

    `""` is the strict reading and the right default: with no sanctioned illegibility declared,
    every unreadable string in a frame is a real defect.
    """
    if style is None:
        return ""
    prose = [style.render_prompt, *style.per_format_guidance.values(), *style.exclusions]
    kept: list[str] = []
    for block in prose:
        for sentence in _SENTENCE.split(str(block or "")):
            clean = " ".join(sentence.split())
            folded = clean.casefold()
            if clean and clean not in kept and any(w in folded for w in _ILLEGIBLE_WORDS):
                kept.append(clean)
    return " ".join(kept)[:_ILLEGIBLE_MAX]


# --------------------------------------------------------------------------- the receipt (§6)


def verdict_result(report: Any, *, rerendered: bool = False) -> VisionCheckResult:
    """The gauntlet's verdict in FR-27's four-state vocabulary — `meta.yaml.vision_check_result`.

    The field survives the deletion of the FR-105 check it was named for, and it is not a stub: its
    four states answer "was this creative read back at all, did it need a second render, and did it
    end clean", which is exactly what the gauntlet's terminal answers and exactly what the gallery
    badge, the spend surfaces and a Phase-2 publisher read. Mapping it is the migration; leaving it
    permanently `not_checked` beside a gate that ran would be a lie in an operator-facing document.

        pass, no re-render      -> PASSED           (it came back right the first time)
        pass, after re-renders  -> RETRIED_PASSED   (a defect was found AND fixed)
        blocked / degraded /
        budget_stop /
        deadline_stop           -> RETRIED_FAILED   (a defect the operator can see is standing)
        skipped / gate off      -> NOT_CHECKED      (nothing read it back)

    The full receipt is `meta.yaml.gauntlet` (spec §6) — this is the one-word summary beside it.
    """
    if report is None or report.result == "skipped":
        return VisionCheckResult.NOT_CHECKED
    if report.result != "pass":
        return VisionCheckResult.RETRIED_FAILED
    return VisionCheckResult.RETRIED_PASSED if rerendered else VisionCheckResult.PASSED


def report_meta(report: Any) -> dict[str, Any] | None:
    """`meta.yaml.gauntlet` — spec §6's shape, written on EVERY terminal path the gate touched.

    A plain dict rather than the report object, because `models.AssetRecord` sits at the bottom of
    the import graph and `gauntlet` imports it (`AssetRecord.gauntlet: dict | None`). `None` when
    the gate never ran at all — a disabled gate, a preview, a deck that delivered nothing — which
    reads in `meta.yaml` as `gauntlet: null` and says exactly that.

    `rounds[].critics` is a per-critic FAIL COUNT rather than the defects themselves: this document
    is the machine-readable summary a spend table and a gallery badge are built from, and the full
    per-frame, per-critic, per-round detail lives beside it in `GAUNTLET_REPORT.yaml` (decision 4A).
    """
    if report is None:
        return None
    return {
        "result": report.result,
        "degraded_gate": bool(report.degraded_gate),
        "craft_only": bool(getattr(report, "craft_only", False)),
        "rounds": [{
            "round": verdict.round,
            "unavailable": list(verdict.unavailable),
            "critics": {name: sum(1 for row in rows if row.defects)
                        for name, rows in verdict.per_critic.items()},
            "failed_frames": list(verdict.failed_frames()),
            "rerendered": list(getattr(verdict, "rerendered", ())),
        } for verdict in report.rounds],
        "rerenders": int(report.rerenders),
        "rerender_cost_usd": round(float(report.rerender_cost_usd), 6),
        "critic_cost_usd": round(float(report.critic_cost_usd), 6),
    }


def report_rows(report: Any, *, asset_id: str = "") -> dict[str, Any]:
    """`GAUNTLET_REPORT.yaml` — every defect every critic named, per frame, per round (spec §6).

    The operator-readable half of the receipt, and the ONLY place a critic's own `detail` string is
    written to an asset folder. That is safe here and nowhere else: this file is read by a person,
    it is never published, and FR-323's whole rule is that critic free text may not reach a RENDER
    payload — the fix channel is canned sentences keyed by `(code, zone)` and never these words.
    """
    return {
        "asset_id": asset_id,
        "result": report.result,
        "degraded_gate": bool(report.degraded_gate),
        "rerenders": int(report.rerenders),
        "critic_cost_usd": round(float(report.critic_cost_usd), 6),
        "rerender_cost_usd": round(float(report.rerender_cost_usd), 6),
        "rounds": [{
            "round": verdict.round,
            "unavailable": list(verdict.unavailable),
            "rerendered": list(getattr(verdict, "rerendered", ())),
            "defects": [{"critic": name, "frame": row.frame, "code": defect.code,
                         "zone": defect.zone, "confidence": defect.confidence,
                         "detail": defect.detail}
                        for name, rows in verdict.per_critic.items()
                        for row in rows for defect in row.defects],
        } for verdict in report.rounds],
    }


#: The plain-language paragraph `BLOCKED.txt` opens with. One sentence per thing the operator has
#: to know: what happened, what it cost, that the files are still there, and where to read why.
_BLOCKED_TEXT = (
    "This creative was BLOCKED by the post-render quality gate and was NOT published.\n"
    "\n"
    "Three independent critics looked at the frames the render provider actually returned and "
    "judged them against what this creative was ordered to carry — its exact words, the logos it "
    "must and must not show, and the style it was rendered in. After {rounds} round(s) and "
    "{rerenders} re-render(s), these defects were still standing:\n"
    "\n"
    "{defects}\n"
    "\n"
    "Nothing was deleted. Every slide, the caption and the metadata are in this folder exactly as "
    "they were paid for, so you can look at them and decide for yourself. What blocking means is "
    "only this: the run did not publish it, its source post was NOT burnt in the no-repeat window "
    "(so tomorrow's run may quote that post again), and the run exits with code 1.\n"
    "\n"
    "The full critic report — every defect, every critic, every round, with the critic's own "
    "wording — is in GAUNTLET_REPORT.yaml beside this file. meta.yaml carries the same verdict "
    "under `gauntlet:`. To ship without this gate, set run.gauntlet.enabled: false in your config "
    "or pass --no-gauntlet.\n")


def blocked_text(report: Any) -> str:
    """`BLOCKED.txt` — why this creative is being held back, in plain English (spec §6).

    Written for an operator who has just opened a folder full of finished slides and wants to know
    why they are not in the gallery. It names the standing defects as `code — where — the critic's
    own note`, one per line, because "invented_text on slide 4" is actionable and "quality gate
    failed" is not.
    """
    standing = report.rounds[-1] if report.rounds else None
    lines = sorted({
        f"  - {defect.code} on frame {row.frame}"
        + (f" ({defect.zone.replace('_', ' ')})" if defect.zone else "")
        + (f" — {defect.detail}" if defect.detail else "")
        for name, rows in (standing.per_critic.items() if standing is not None else ())
        for row in rows for defect in row.defects})
    return _BLOCKED_TEXT.format(
        rounds=len(report.rounds), rerenders=report.rerenders,
        defects="\n".join(lines) or "  - (the gate stopped before it could name one)")


__all__ = ["blocked_text", "creator_forms", "deck_contract", "forbidden_terms", "frame_contract",
           "gate_on", "panel_facts", "report_meta", "report_rows", "sanctioned_illegible",
           "verdict_result"]
