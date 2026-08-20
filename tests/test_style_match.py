"""`hypesocials.style_match` — the matched style overlay at ASSIGN (FR-334, D56).

The module is an OVERLAY on the FR-291 rotation baseline, and almost everything worth pinning
here is a way that overlay declines to act:

* the baseline stands on every rejection — a `low` fit, a key outside THIS creative's own ballot,
  a row that never came back, a row that came back twice — and `Match.style_key` is EMPTY on all
  of them, because the caller writes `entry.style_key = pick.style_key or entry.style_key` and a
  matcher that echoed the baseline back could not be told apart from one that chose it;
* the whole call is **fail-open**, exactly like the topic screen (§1.5) and slide intelligence
  (§0.14c): no llm, a raising llm, a degraded or unparseable answer all come back total, on
  `rotation_fallback`, with the `style_match_degraded:` marker the caller turns into ONE operator
  warning and one degradation tag. A matcher we could not run assigns styles the way v2.3.0
  assigned them; it never loses a plan;
* answers join on **`asset_id` and never on ordinal**. That is the bug class this file exists to
  freeze: an ordinal join is what produced the W5 renumbering defect (`runner.py:438-447`), where
  one dropped row slid every later answer onto its predecessor's creative;
* the candidate pool is `styles.usable_styles` narrowed by `styles.fmt_affine`, **imported, never
  re-derived**, so a `carousel_role: slides_only` style can no more be MATCHED onto a deck than it
  could be ROTATED onto one.

Two output-side properties get their own tests because the strings involved reach three surfaces a
person reads (the ASSIGN receipt, `meta.yaml`, an HTML gallery card): a provider error is reported
by its exception CLASS NAME alone (D30 — an error body can carry a URL, a payload or a key), and
every model-authored string comes back single-line, control-character-free and length-bounded.

Offline and deterministic like `test_topic_filter.py`, whose fake-`StructuredCall` pattern this
file follows: no network, no API key, no `output/` and no `logs/` writes. The prompt IS rendered
here — `prompts/style_match_system.md` is a repo file read, and rendering it is what lets these
tests inspect the ballot the model was actually shown instead of a private function's return.
"""

from __future__ import annotations

from typing import Any

import pytest

from hypesocials import style_match
from hypesocials.config import CONFIGS_DIR, BrandingConfig, Config, StylesConfig, load_config
from hypesocials.models import MetaStyle, ParsedResult, PlanEntry, SourcePost, TrendItem
from hypesocials.prompts_engine import PROMPTS_DIR
from hypesocials.styles import StyleRegistry, fmt_affine, load_registry, usable_styles

TOPIC_KEY = "m1::t1"

#: A deliberately synthetic, obviously-fake credential shape. It is NOT a key, it is the thing a
#: provider error body looks like — the string the D30 test below proves never reaches an operator.
FAKE_KEY_IN_A_URL = ("https://openrouter.test/v1/chat/completions"
                     "?api_key=sk-or-v1-THIS-IS-NOT-A-REAL-KEY-0000")


# --------------------------------------------------------------------------- builders


def _style(key: str, **over: Any) -> MetaStyle:
    """One registry entry that is affine to every format, so a test's own overrides are the
    only reason a style is ever out of a pool."""
    fields: dict[str, Any] = {
        "render_prompt": "Flat graphic card, centred subject, hard shadow, wide margins.",
        "match_profile": f"Suits source decks the {key} look was drawn for.",
        "format_affinity": ["image", "carousel", "reel"],
    }
    fields.update(over)
    return MetaStyle(key=key, **fields)


def _registry(*entries: MetaStyle) -> StyleRegistry:
    return StyleRegistry(version=1, styles=list(entries), origin="prompts/styles.yaml",
                         content_hash="0123456789ab")


def _config(*, enabled: list[str] | None = None, brand: str = "hypedigitaly") -> Config:
    return Config(branding=BrandingConfig(brand=brand),
                  styles=StylesConfig(enabled=list(enabled or []), assignment="matched"))


def _entry(order: int, fmt: str = "carousel", *, baseline: str = "alpha",
           **over: Any) -> PlanEntry:
    """One live plan entry as ASSIGN leaves it: `styles.assign_styles` has already written
    `style_key`, which is the baseline every rejection below must leave standing."""
    fields: dict[str, Any] = {
        "order": order,
        "asset_id": f"a{order:02d}",
        "creative_format": fmt,
        "platform": "linkedin",
        "language": "en",
        "aspect_ratio": "4:5",
        "style_key": baseline,
        "trend_key": TOPIC_KEY,
    }
    fields.update(over)
    return PlanEntry(**fields)  # type: ignore[arg-type]


def _topics(panels: int = 4) -> dict[str, TrendItem]:
    """The run's topics by `history_key` — `entry.trend_key`'s key space, as `runner` builds it."""
    post = SourcePost(post_id="p1", url="https://virlo.test/p1", author="@someone",
                      caption="what nobody tells you about pricing pages",
                      hooks=["nobody tells you this"], is_slideshow=True, panel_count=panels,
                      panel_texts=[f"panel {index} words" for index in range(panels)],
                      views=4_900_000)
    return {TOPIC_KEY: TrendItem(history_key=TOPIC_KEY, monitor_id="m1", topic_key="t1",
                                 name="pricing pages that quietly convert", strength=0.81,
                                 why_it_works="the numbers do the arguing",
                                 hook_types=["story_tease"], visual_hook_types=["text_card"],
                                 emotional_tones=["curiosity"],
                                 engagement={"likes": 12_400, "comments": 210}, posts=[post])}


def _row(asset_id: str, style_key: str = "", fit: str = "high", reason: str = "it fits",
         wanted: str = "") -> dict[str, Any]:
    """One row of the wire shape `style_match` parses: `{"matches": [...]}` (FR-335)."""
    return {"asset_id": asset_id, "style_key": style_key, "fit": fit, "reason": reason,
            "wanted_archetype": wanted}


class Answer:
    """A `models.StructuredCall` returning crafted match rows and remembering every call.

    Honours the pinned protocol shape — `async (role, messages, json_schema, images=None)` — which
    is the only seam `match()` has; a stub that drifted from it would test a signature no run uses.
    The recorded `messages` are how the tests below read the prompt the model was really shown.
    """

    def __init__(self, *rows: dict[str, Any], raises: Exception | None = None,
                 parsed: Any = ..., degraded: bool = False, reason: str = "") -> None:
        self.rows = list(rows)
        self.raises = raises
        self.parsed = parsed
        self.degraded = degraded
        self.reason = reason
        self.calls: list[tuple[str, list[dict[str, Any]], dict[str, Any], Any]] = []

    async def __call__(self, role: str, messages: list[dict[str, Any]],
                       json_schema: dict[str, Any], images: list[bytes] | None = None
                       ) -> ParsedResult:
        self.calls.append((role, messages, json_schema, images))
        if self.raises is not None:
            raise self.raises
        parsed = {"matches": self.rows} if self.parsed is ... else self.parsed
        return ParsedResult(parsed=parsed, raw_text="{}", degraded=self.degraded,
                            reason=self.reason)

    @property
    def prompt(self) -> str:
        """The rendered system prompt of the one batched call."""
        assert len(self.calls) == 1, f"expected exactly one call, got {len(self.calls)}"
        return str(self.calls[0][1][0]["content"])


def _offered(prompt: str) -> set[str]:
    """Every style key named on any per-entry `candidates:` line — the union of the ballots.

    Read off the prompt rather than off `style_match._ballots`, because what the model may answer
    with is what the model was SHOWN, and the private function is only how it got there.
    """
    keys: set[str] = set()
    for line in prompt.splitlines():
        if line.startswith("candidates: "):
            keys.update(part.strip() for part in line[len("candidates: "):].split(",") if
                        part.strip())
    return keys


def _sections(prompt: str) -> list[str]:
    """The `asset_id:` of every creative the prompt actually carries a section for."""
    return [line[len("asset_id: "):].strip() for line in prompt.splitlines()
            if line.startswith("asset_id: ")]


# --------------------------------------------------------------------------- totality


async def test_every_entry_comes_back_with_a_match_whatever_the_model_said() -> None:
    """The mapping is TOTAL by contract: the caller must never have to ask whether a creative was
    matched, and must never have to guard a `KeyError` around a style assignment."""
    registry = _registry(_style("alpha"), _style("beta"), _style("gamma"))
    entries = [_entry(index) for index in range(4)]

    picks = await style_match.match(entries, registry, _topics(), _config(),
                                    Answer(_row("a01", "beta")))

    assert sorted(picks) == ["a00", "a01", "a02", "a03"]
    assert all(isinstance(pick, style_match.Match) for pick in picks.values())
    assert all(picks[asset_id].asset_id == asset_id for asset_id in picks)
    assert picks["a01"].origin == style_match.ORIGIN_MATCHED
    assert {picks[key].origin for key in ("a00", "a02", "a03")} == {style_match.ORIGIN_ROTATION}


async def test_the_matcher_answers_and_never_writes_to_the_plan_entries_itself() -> None:
    """An OVERLAY, and the caller owns the write. `match()` returns `Match` objects and touches no
    entry, which is what lets `runner._assign_visuals` stamp provenance in one place and what makes
    `Match.style_key` an OVERRIDE rather than an outcome — empty means "the baseline stands"."""
    registry = _registry(_style("alpha"), _style("beta"))
    entries = [_entry(0, baseline="alpha"), _entry(1, baseline="alpha")]

    picks = await style_match.match(entries, registry, _topics(), _config(),
                                    Answer(_row("a00", "beta"), _row("a01", "beta", "low")))

    assert picks["a00"].style_key == "beta" and picks["a01"].style_key == ""
    assert [entry.style_key for entry in entries] == ["alpha", "alpha"], \
        "the module may not assign a style; it may only answer which one to assign"
    assert all(entry.style_origin == "" and entry.style_fit == "" for entry in entries)


# --------------------------------------------------------------------------- pool validation


async def test_a_style_key_outside_this_creatives_ballot_is_rejected_and_the_baseline_stands(
) -> None:
    """Gate two of `_apply`: the key has to be one THIS creative was offered. Without it the pool
    predicates would be advisory — a model that read the vocabulary block (or invented a key
    outright) could assign a style the rotation is forbidden to give the same creative.

    The reason is the ENGINE's sentence, not the model's: the model argued for a style this
    creative cannot wear, so its own sentence would explain the wrong outcome on the receipt.
    """
    registry = _registry(_style("alpha"), _style("beta"))
    entry = _entry(0, baseline="alpha")

    picks = await style_match.match([entry], registry, _topics(), _config(),
                                    Answer(_row("a00", "a-style-nobody-authored", "high",
                                                "this look is perfect for the deck")))

    pick = picks["a00"]
    assert pick.origin == style_match.ORIGIN_ROTATION
    assert pick.style_key == "" and pick.fit == ""
    assert "not a candidate for this creative" in pick.reason
    assert "a-style-nobody-authored" in pick.reason, "the operator is told what was asked for"
    assert "perfect for the deck" not in pick.reason, "and not the argument for the wrong outcome"
    assert entry.style_key == "alpha"


async def test_a_key_the_fr314_selector_excluded_is_rejected_even_though_the_registry_has_it(
) -> None:
    """The ballot is `usable_styles` narrowed by `fmt_affine`, so the FR-314 selector binds the
    matcher exactly as it binds the rotation. A style the operator deselected for this run is not
    a style this run may wear, whichever algorithm names it."""
    registry = _registry(_style("alpha"), _style("beta"), _style("deselected"))
    config = _config(enabled=["alpha", "beta"])

    answer = Answer(_row("a00", "deselected", "high"))
    picks = await style_match.match([_entry(0)], registry, _topics(), config, answer)

    assert picks["a00"].origin == style_match.ORIGIN_ROTATION and picks["a00"].style_key == ""
    assert _offered(answer.prompt) == {"alpha", "beta"}
    assert "deselected" not in answer.prompt, "a deselected style is not even described"


# --------------------------------------------------------------------------- the fit fork


async def test_a_low_fit_keeps_the_baseline_and_preserves_the_archetype_the_model_wanted(
) -> None:
    """The one rejection the model MEANT: it read the ballot and said none of it fits.

    `wanted_archetype` survives the fall back to baseline because it IS the gap report (D56
    decision 3) — the engine never synthesizes a style at runtime (FR-295 registry authority), so
    the miss is written down and the operator authors the missing style deliberately. The `low`
    travels with it too: `rotation · low` is the line telling an operator this creative wears an
    arbitrary style, which a blank fit beside a rotation pick would not say.
    """
    registry = _registry(_style("alpha"), _style("beta"))

    picks = await style_match.match(
        [_entry(0, baseline="alpha")], registry, _topics(), _config(),
        Answer(_row("a00", "beta", "low", "nothing here sets a numbered list",
                    "numbered listicle card deck")))

    pick = picks["a00"]
    assert pick.origin == style_match.ORIGIN_ROTATION
    assert pick.style_key == "", "the baseline stands, and the pick does not echo it back"
    assert pick.fit == style_match.FIT_LOW
    assert pick.wanted_archetype == "numbered listicle card deck"
    assert pick.reason == "nothing here sets a numbered list"


async def test_a_medium_fit_accepts_the_pick_exactly_as_a_high_one_does() -> None:
    """`medium` ACCEPTS (FR-335). "No candidate is a natural home but this one will not fight the
    content" is still a content-AWARE choice, and the only alternative on offer is a content-BLIND
    one. So the two accepting levels differ in one place and one place only: the `fit` string.

    The accepted row's `wanted_archetype` is dropped rather than carried — an accepted style has no
    gap, and keeping it would pollute the gap report with archetypes the run already covered.
    """
    registry = _registry(_style("alpha"), _style("beta"), _style("gamma"))
    plan = [_entry(0, baseline="alpha"), _entry(1, baseline="alpha")]

    picks = await style_match.match(
        plan, registry, _topics(), _config(),
        Answer(_row("a00", "beta", "high", "dense panels, graphic ground"),
               _row("a01", "gamma", "medium", "no natural home, this one will not fight it",
                    "a photo-led statement deck")))

    high, medium = picks["a00"], picks["a01"]
    assert (high.style_key, high.origin) == ("beta", style_match.ORIGIN_MATCHED)
    assert (medium.style_key, medium.origin) == ("gamma", style_match.ORIGIN_MATCHED)
    assert (high.fit, medium.fit) == (style_match.FIT_HIGH, style_match.FIT_MEDIUM)
    assert medium.wanted_archetype == "", "an accepted style has no gap to report"


async def test_a_fit_word_outside_the_three_rejects_the_pick_and_keeps_the_archetype() -> None:
    """The model is an external input, so its `fit` is validated at the boundary rather than
    trusted to be one of three words. `perfect` is not an accept by accident: an unreadable
    confidence beside an assigned style would read as "high fit, assigned anyway"."""
    registry = _registry(_style("alpha"), _style("beta"))

    picks = await style_match.match(
        [_entry(0)], registry, _topics(), _config(),
        Answer(_row("a00", "beta", "perfect", "spot on", "a terminal walkthrough deck")))

    assert picks["a00"].origin == style_match.ORIGIN_ROTATION
    assert picks["a00"].style_key == "" and picks["a00"].fit == ""
    assert picks["a00"].wanted_archetype == "a terminal walkthrough deck"


# --------------------------------------------------------------------------- fail-open


@pytest.mark.parametrize("llm, why", [
    pytest.param(None, "no model call available", id="no-llm"),
    pytest.param(Answer(raises=RuntimeError("provider down")), "raised", id="raising"),
    pytest.param(Answer(degraded=True, reason="truncated"), "degraded", id="degraded"),
    pytest.param(Answer(parsed=None), "not a JSON object", id="unparseable"),
    pytest.param(Answer(parsed={"nothing": "useful"}), "no `matches` list", id="wrong-shape"),
])
async def test_a_missing_or_broken_matcher_puts_every_entry_on_the_baseline_and_says_so_once(
    llm: Any, why: str,
) -> None:
    """Fail-OPEN with a marker, the `filter_degraded` posture verbatim (FR-294 → FR-334).

    Every entry comes back — including entries the prompt never reached — on `rotation_fallback`
    with `style_match_degraded: <cause>`, so the CALLER raises ONE operator warning and appends one
    degradation tag instead of N of each. Nothing raises out of `match()`: it is total by contract
    and the caller has no fallback path of its own.
    """
    registry = _registry(_style("alpha"), _style("beta"))
    plan = [_entry(0, baseline="alpha"), _entry(1, baseline="beta"), _entry(2, baseline="alpha")]

    picks = await style_match.match(plan, registry, _topics(), _config(), llm)

    assert sorted(picks) == ["a00", "a01", "a02"]
    assert {pick.origin for pick in picks.values()} == {style_match.ORIGIN_FALLBACK}
    assert all(pick.style_key == "" for pick in picks.values()), "every baseline stands"
    assert all(pick.reason.startswith(f"{style_match.DEGRADED_MARKER}: ")
               for pick in picks.values())
    assert all(why in pick.reason for pick in picks.values()), \
        "the cause is named, not merely tagged"
    assert [entry.style_key for entry in plan] == ["alpha", "beta", "alpha"]


async def test_the_degraded_marker_is_the_degradation_tags_own_spelling() -> None:
    """One fact, one spelling: the console line, the `meta.yaml` tag and this marker are the same
    string taken from `DegradationTag.STYLE_MATCH_DEGRADED` rather than typed out three times."""
    from hypesocials.models import DegradationTag

    assert style_match.DEGRADED_MARKER == DegradationTag.STYLE_MATCH_DEGRADED.value
    assert style_match.DEGRADED_MARKER == "style_match_degraded"


# --------------------------------------------------------------------------- the asset_id join


async def test_answers_join_on_asset_id_so_a_shuffled_answer_still_lands_on_its_own_creative(
) -> None:
    """THE ordinal-join regression, frozen. This is the defect class `runner.py:438-447` records:
    a positional join means one dropped or reordered row slides every later answer onto its
    predecessor's creative — silently, in paid output, with a plausible-looking receipt.

    The answer below is deliberately shuffled AND short one row. Under an ordinal join `a00` would
    wear `gamma` (row 1), `a01` would wear `beta` (row 2) and `a02` would wear `delta` (row 3);
    under the asset_id join each wears the style its own row names and `a01` — which no row names
    — keeps its rotation baseline. Every assertion below therefore fails on a positional join.
    """
    registry = _registry(_style("alpha"), _style("beta"), _style("gamma"), _style("delta"))
    plan = [_entry(index, baseline="alpha") for index in range(4)]

    picks = await style_match.match(
        plan, registry, _topics(), _config(),
        Answer(_row("a02", "gamma"), _row("a00", "beta"), _row("a03", "delta")))

    assert picks["a00"].style_key == "beta"
    assert picks["a02"].style_key == "gamma"
    assert picks["a03"].style_key == "delta"
    assert picks["a01"].style_key == "" and picks["a01"].origin == style_match.ORIGIN_ROTATION
    assert picks["a01"].reason == "", "an unanswered creative carries no explanation it never got"


async def test_an_unknown_asset_id_is_ignored_and_a_duplicated_one_decides_nothing() -> None:
    """Three discards, each leaving that creative on its rotation baseline.

    An id that is not this run's is invention — a creative the prompt did not contain cannot have
    been judged. A SECOND row for an id already answered makes NEITHER authoritative: taking the
    first (or the last) would let a model that lost count silently re-style a creative on a coin
    flip, and which row won would depend on answer order — the very thing the asset_id join exists
    to remove. And a well-formed row still lands: the repair is per row, never a blanket discard.
    """
    registry = _registry(_style("alpha"), _style("beta"), _style("gamma"))
    plan = [_entry(index, baseline="alpha") for index in range(3)]

    picks = await style_match.match(
        plan, registry, _topics(), _config(),
        Answer(_row("a00", "beta"),
               _row("a01", "beta"), _row("a01", "gamma"),
               _row("not-in-this-run", "gamma"),
               _row("", "gamma")))

    assert sorted(picks) == ["a00", "a01", "a02"]
    assert picks["a00"].style_key == "beta", "one well-formed row still lands"
    assert picks["a01"].style_key == "" and picks["a01"].origin == style_match.ORIGIN_ROTATION
    assert picks["a01"].fit == "", "two rows named it, so neither of them decides anything"
    assert picks["a02"].style_key == "", "no row named it"
    assert len(picks) == 3, "an unknown id creates no creative"


# ------------------------------------------------- the imported pool predicates (fmt_affine)


async def test_a_slides_only_style_is_never_a_carousel_candidate_and_is_refused_if_named(
) -> None:
    """`carousel_role: slides_only` is read by `styles.fmt_affine` and by nothing else.

    Under anchor chaining slide 1 IS the deck's style, so a slides-only style can never take a
    carousel ENTRY at all — and that has to be true of matched assignment for the same reason it is
    true of the rotation, or the two algorithms disagree about what a run may wear. Both halves are
    pinned: the key is not offered (the model cannot reach it), and naming it anyway is refused
    (the model reaching it by other means changes nothing).
    """
    # The key is deliberately a string no English prose contains, because the assertion below is
    # about the whole PROMPT and the template itself talks about panels, slides, decks and rows.
    slides_only = "fixture-slides-only-look"
    registry = _registry(_style("alpha"), _style("beta"),
                         _style(slides_only,
                                per_format_guidance={"carousel_role": "slides_only"}))

    deck = Answer(_row("a00", slides_only, "high"))
    on_deck = await style_match.match([_entry(0, "carousel")], registry, _topics(),
                                      _config(), deck)

    assert _offered(deck.prompt) == {"alpha", "beta"}
    assert slides_only not in deck.prompt, \
        "the vocabulary block may not advertise a key no ballot can reach"
    assert on_deck["a00"].origin == style_match.ORIGIN_ROTATION
    assert on_deck["a00"].style_key == ""

    # ... and the same style on an IMAGE entry is an ordinary candidate: `slides_only` narrows one
    # format, not the style, which is exactly what re-deriving the rule tends to get wrong.
    still = Answer(_row("a00", slides_only, "high"))
    on_image = await style_match.match([_entry(0, "image")], registry, _topics(), _config(), still)

    assert slides_only in _offered(still.prompt)
    assert on_image["a00"].style_key == slides_only
    assert on_image["a00"].origin == style_match.ORIGIN_MATCHED


async def test_the_shipped_registrys_slides_only_styles_reach_no_carousel_ballot() -> None:
    """The same predicate against the REAL artifacts (26 styles since D61 — 19 at D56/D57 plus
    the seven carousel-derived D61 entries, none of which is `slides_only`), because the fake
    registry above cannot catch a `carousel_role` spelling that drifted in `prompts/styles.yaml`.

    Four shipped styles carry `slides_only` — `meme-caricature-panels`, `ugc-tabletop-statement`
    and both their `-teal` variants — and two of the four sit inside the 17-key `styles.enabled`
    set the brand configs ship, so a carousel-only run genuinely has them in the registry, in the
    selection, and out of the ballot. The ballot is compared against `usable_styles` × `fmt_affine`
    computed here from the same inputs: what the matcher offers IS what the rotation scans, and
    this test fails the moment `style_match` grows its own copy of either predicate.
    """
    registry = load_registry([PROMPTS_DIR])
    config = load_config("hypedigitaly", configs_dir=CONFIGS_DIR)
    slides_only = {style.key for style in registry.styles
                   if style.per_format_guidance.get("carousel_role") == "slides_only"}
    assert len(slides_only) == 4, f"the D56/D57 registry ships four, found {sorted(slides_only)}"
    assert slides_only & set(config.styles.enabled), \
        "and the shipped selection admits some of them"

    answer = Answer(_row("a00", "", "low", "none of these", "a numbered listicle deck"))
    await style_match.match([_entry(0, "carousel")], registry, _topics(), config, answer)

    offered = _offered(answer.prompt)
    pool = usable_styles(registry, config.branding.brand, config.styles.enabled,
                         branding_enabled=config.branding.enabled)
    assert offered == {style.key for style in pool if fmt_affine(style, "carousel")}
    assert not offered & slides_only, "no slides-only style may anchor a deck (fmt_affine)"
    assert offered, "the fixture must still leave a real choice, or it proves nothing"


# --------------------------------------------------------------------------- D30 + sanitizing


async def test_a_provider_error_reaches_the_operator_as_a_class_name_and_never_as_its_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D30, at the one boundary where a third-party error body meets an operator-facing string.

    `reason` is printed on the ASSIGN receipt, written into `meta.yaml` and rendered onto a gallery
    card. A provider's exception message can carry the request URL — and a URL can carry a key, a
    token or a payload — so the provider-side catch logs the exception CLASS NAME and nothing else.
    The class name is the useful half and is asserted present: "something failed" with no name is
    an operator who cannot tell a timeout from a 402.
    """

    class ProviderCallFailed(RuntimeError):
        """A provider error whose message is exactly what must not be repeated."""

    boom = ProviderCallFailed(f"POST {FAKE_KEY_IN_A_URL} returned 401 for org acme-internal")
    registry = _registry(_style("alpha"), _style("beta"))

    with caplog.at_level("DEBUG", logger="hypesocials.style_match"):
        picks = await style_match.match([_entry(0), _entry(1)], registry, _topics(), _config(),
                                        Answer(raises=boom))

    for pick in picks.values():
        assert pick.origin == style_match.ORIGIN_FALLBACK
        assert pick.reason == (f"{style_match.DEGRADED_MARKER}: the match call raised "
                               "ProviderCallFailed")
        for leak in ("sk-or", "api_key", "openrouter", "http", "401", "acme-internal"):
            assert leak not in pick.reason, f"{leak!r} must not reach an operator-facing string"
    # The run log is the same boundary: nothing the module logs may carry the body either.
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "ProviderCallFailed" in logged
    assert "sk-or" not in logged and "acme-internal" not in logged


async def test_a_model_authored_string_comes_back_one_line_control_free_and_length_bounded(
) -> None:
    """`reason` and `wanted_archetype` are model-authored prose that lands on a console line, in
    `meta.yaml` and inside HTML gallery markup, so they are sanitized ONCE — here, at the boundary
    where they stop being an answer and start being output — rather than by each of the three.

    Control characters go first and by SUBSTITUTION: a newline breaks the receipt's one-line-per-
    creative shape, and an ESC run reaching a console is an ANSI sequence that is EXECUTED rather
    than read. Length comes second, at the module's published bounds (160 / 72 characters), which
    are roughly double the specified answer sizes — an obedient model is never cut and a runaway
    one cannot push a 4 kB paragraph through three surfaces.
    """
    nasty = ("first line\nsecond line\x1b[31m\x07 tabbed\there " + "padding " * 40).strip()
    registry = _registry(_style("alpha"), _style("beta"))

    rejected = await style_match.match(
        [_entry(0)], registry, _topics(), _config(),
        Answer(_row("a00", "beta", "low", nasty, nasty)))
    accepted = await style_match.match(
        [_entry(0)], registry, _topics(), _config(),
        Answer(_row("a00", "beta", "high", nasty)))

    for text, limit in ((rejected["a00"].reason, 160),
                        (rejected["a00"].wanted_archetype, 72),
                        (accepted["a00"].reason, 160)):
        assert text, "the string is sanitized, never blanked"
        assert len(text) <= limit, f"{len(text)} chars is over the {limit}-char bound"
        assert "\n" not in text and "\r" not in text and "\t" not in text
        assert "\x1b" not in text and "\x07" not in text
        assert not any(ord(char) < 32 or ord(char) == 127 for char in text), \
            "no control character survives to a console, meta.yaml or a gallery card"
    assert accepted["a00"].style_key == "beta", "sanitizing never costs the creative its pick"


# ------------------------------------------------- nothing in scope: a no-op, not a degrade


@pytest.mark.parametrize("registry, plan, why", [
    pytest.param(_registry(_style("alpha"), _style("beta")),
                 [PlanEntry(order=0, asset_id="a00",  # type: ignore[arg-type]
                            creative_format="carousel", platform="linkedin", language="en",
                            aspect_ratio="4:5", brief_name="ai-audit-cta",
                            brief_influence="override")],
                 "an override brief is never styled at all (M14)", id="override-only"),
    pytest.param(_registry(_style("alpha")), [_entry(0), _entry(1)],
                 "a ballot with one name on it is a question already answered", id="one-style"),
    pytest.param(_registry(_style("alpha"), _style("only-image", format_affinity=["image"])),
                 [_entry(0, "carousel")],
                 "one style is affine to this format, so there is no choice", id="one-affine"),
    pytest.param(None, [_entry(0)], "a registry-less run has no styles to match at all",
                 id="no-registry"),
])
async def test_a_plan_with_nothing_to_choose_between_makes_no_call_and_is_not_a_degrade(
    registry: Any, plan: list[PlanEntry], why: str,
) -> None:
    """The deliberate deviation from the plan's literal wording, pinned so it is not "fixed" back.

    With NOTHING in scope the call is skipped and every entry comes back on `rotation` — NOT on
    `rotation_fallback`, and NOT tagged, even with `llm=None`. A matcher with nothing to choose
    between has not failed: it had no question. Degrading there would raise a false operator
    warning and stamp `style_match_degraded` onto every asset of a run in which nothing went wrong,
    which is exactly the noise that teaches an operator to ignore the tag when it is real.

    Each case is also $0 by construction — no ballot, no prompt, no tokens.
    """
    picks = await style_match.match(plan, registry, _topics(), _config(), None)

    assert sorted(picks) == sorted(entry.asset_id for entry in plan)
    assert {pick.origin for pick in picks.values()} == {style_match.ORIGIN_ROTATION}, why
    assert all(pick.reason == "" for pick in picks.values()), "nothing degraded, so nothing to say"
    assert all(style_match.DEGRADED_MARKER not in pick.reason for pick in picks.values())
    assert all(pick.style_key == "" and pick.fit == "" for pick in picks.values())

    # ... and with a live llm in hand it still buys nothing: the skip is about the QUESTION, not
    # about whether a model was available to answer it.
    recorder = Answer(_row("a00", "alpha", "high"))
    again = await style_match.match(plan, registry, _topics(), _config(), recorder)

    assert recorder.calls == [], "a question already answered is never asked, and never billed"
    assert {pick.origin for pick in again.values()} == {style_match.ORIGIN_ROTATION}


async def test_an_override_brief_is_never_styled_and_never_consumes_prompt_space() -> None:
    """M14: an override brief's directives replace the style channel outright, so it carries no
    `style_key` for a matcher to overrule (`runner._assign_visuals` filters it out before
    `assign_styles` ever sees it). This module filters it again as defence in depth.

    "Never consumes prompt space" is the half worth a test: the entry is absent from the rendered
    prompt entirely — no section, no ballot, no tokens — so a plan that is half briefs prices and
    sends a prompt sized to the creatives that are actually being styled.

    The answer below also names the brief, which is the one shape a live run cannot produce
    (`_assign_visuals` filters override entries out before the matcher is called, so the model is
    never shown one) and which the module still has to survive: an id with no ballot is an id that
    was never judged, so nothing it says can be accepted. The engine's own rejection sentence lands
    on `reason` rather than the model's argument for the wrong outcome — the same fork as an
    out-of-pool key, because "offered nothing" is the limit case of "not one of its candidates".
    """
    registry = _registry(_style("alpha"), _style("beta"), _style("gamma"))
    brief = _entry(0, brief_name="ai-audit-cta", brief_influence="override", baseline="")
    styled = _entry(1, baseline="alpha")
    answer = Answer(_row("a01", "beta"),
                    _row("a00", "gamma", "high", "the brief deck wants the gamma look"))

    picks = await style_match.match([brief, styled], registry, _topics(), _config(), answer)

    assert _sections(answer.prompt) == ["a01"], "only the styled creative is described"
    assert "a00" not in answer.prompt and "ai-audit-cta" not in answer.prompt
    assert picks["a01"].style_key == "beta" and picks["a01"].origin == style_match.ORIGIN_MATCHED
    assert picks["a00"].style_key == "" and picks["a00"].origin == style_match.ORIGIN_ROTATION
    assert picks["a00"].fit == "", "an unjudged creative is never given a confidence"
    assert "not a candidate for this creative" in picks["a00"].reason
    assert "wants the gamma look" not in picks["a00"].reason
    assert brief.style_key == ""


# --------------------------------------------------------------------------- the one batched call


async def test_the_whole_plan_is_matched_in_one_analysis_call_that_carries_no_images() -> None:
    """ONE call per RUN, batched over every entry in scope, on the `analysis` role (Sonnet 5 — the
    same role `slide_intel` runs on, because this is a READING task over third-party text).

    Text-only by contract: no slide is read here and reading one would be FR-306's job, so the
    `images` argument is None — which is also what keeps the budget line's token arithmetic honest.
    """
    registry = _registry(_style("alpha"), _style("beta"), _style("gamma"))
    plan = [_entry(index) for index in range(6)]
    answer = Answer(*[_row(entry.asset_id, "beta") for entry in plan])

    picks = await style_match.match(plan, registry, _topics(), _config(), answer)

    assert len(answer.calls) == 1, "one batched call for the whole plan, never one per creative"
    role, messages, schema, images = answer.calls[0]
    assert role == style_match.MATCH_ROLE == "analysis"
    assert images is None
    assert [message["role"] for message in messages] == ["system", "user"]
    assert schema["name"] == "style_matches"
    assert _sections(answer.prompt) == [entry.asset_id for entry in plan], "plan order, all six"
    assert all(pick.style_key == "beta" for pick in picks.values())
