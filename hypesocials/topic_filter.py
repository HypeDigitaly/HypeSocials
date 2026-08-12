"""Competitor screen — one batched, text-only classify call between Collect and Select (FR-294).

Callers import `hypesocials.topic_filter`. Two calls, one concept — is this topic safe to build a
creative on, and if so which strings must never reach the pixels:

    verdicts = await screen(topics, session.config, llm)   # {ordinal: Verdict}, ALWAYS total
    clean = apply_blocklist(text, session.config.branding.competitors)   # pure, sync, $0

Verdicts key on an ENGINE-ASSIGNED ordinal (1..N in input order), never on `topic_key`: the topic
names come from a competitor's own posts, and a crafted name must not be able to address another
topic's verdict (§1.5, FR-102 fence discipline).

Two layers, deliberately different failure directions:

- **Blocklist (layer 1) is deterministic and FAIL-CLOSED.** `branding.competitors` is applied by
  word-boundary match over the topic name and its candidate strings, and it applies even when the
  model layer is down — "the LLM was unavailable" must never be the reason a competitor's name
  ships in our pixels.
- **The LLM screen (layer 2) is FAIL-OPEN.** No `llm`, a failed call, an unparseable answer: every
  non-blocklist verdict stays `keep` and every returned `Verdict.reason` carries the
  `filter_degraded: <cause>` marker, which `runner._screen_topics` turns into ONE operator warning.
  Filter failure must never couple to copy failure — a screen we could not run is not a reason to
  lose the batch.

The strongest verdict wins where the layers disagree (`skip` > `strip` > `keep`), and a `strip`
whose brand list empties after the M15 guards degrades to `keep`: a strip with nothing to strip is
a keep, not a silent no-op verdict.

Do not: call this before Confirm (it costs money — previews print the layer-1 verdicts only, $0,
labelled as such, FR-139); key verdicts on anything the source controls; import this module from
`copywrite` in a way that closes a cycle — the edge is one-way, `copywrite` imports
`apply_blocklist` from here and this module never imports `copywrite`.

Import edges, both one-way and both deliberate: this module imports `prompts_engine` at module
level (it renders its own system prompt through the one template door), and `prompts_engine`
imports `apply_blocklist` from here LAZILY, inside its M6 strip pass, so the two never close a
cycle at import time. `apply_blocklist` is the single implementation of the strip policy for the
whole codebase — copy, render prompts and previews all resolve "was it stripped" the same way.
"""

from __future__ import annotations

import functools
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .models import StructuredCall, TrendItem
from .prompts_engine import PromptEngine, build_context

logger = logging.getLogger(__name__)

#: Same role config as `copywrite.COPY_ROLE` (Luna, cheap and fast — §1.5). Duplicated as a
#: constant rather than imported, because `copywrite` imports `apply_blocklist` from this module
#: for its verbatim verifier (W2) and the import edge has to stay one-way.
_FILTER_ROLE = "copy"
_TEMPLATE = "topic_filter_system.md"
_CARRIER_TURN = "Return the verdict JSON for the numbered topics above now."

_KEEP, _STRIP, _SKIP = "keep", "strip", "skip"
#: Strength order — where the two layers disagree, the stronger verdict stands.
_RANK = {_KEEP: 0, _STRIP: 1, _SKIP: 2}
#: M15 strip guards. A two-character "brand" is punctuation; a candidate string gutted to under
#: 15 characters was one whose subject WAS the brand, and stripping it ships a sentence fragment.
_MIN_BRAND_CHARS = 3
_MIN_CANDIDATE_CHARS = 15
_MAX_STRIPS = 5  # per topic; a topic needing six strips is a topic to skip, not to sanitize
#: Words a model reaches for when it has no real brand to name. Entries under three characters are
#: already rejected by the length guard, so this list only needs the longer ones.
_STOPWORDS = frozenset({
    "and", "the", "for", "with", "from", "this", "that", "your", "our", "you", "they", "them",
    "new", "app", "apps", "top", "best", "tips", "post", "posts", "video", "videos", "brand",
    "brands", "company", "product", "products", "team", "people", "content", "social", "media",
    "online", "free", "how", "why", "what", "when", "who", "not", "all", "one", "two", "more",
    "pro", "plus", "premium", "official", "trend", "trending", "viral",
})


@dataclass(slots=True)
class Verdict:
    """One topic's screen verdict, keyed by ENGINE-ASSIGNED ordinal (§1.5 — never `topic_key`: a
    crafted topic name must not be able to spoof another topic's verdict).
    """

    ordinal: int  # 1-based, input order
    verdict: str = _KEEP  # "keep" | "strip" | "skip"
    brands_to_strip: list[str] = field(default_factory=list)  # post-guard survivors only
    reason: str = ""


class _FilterUnavailable(RuntimeError):
    """Layer 2 could not produce an answer. Caught in `screen()`; the run degrades, never fails."""


# --------------------------------------------------------------------------------------------
# The screen
# --------------------------------------------------------------------------------------------


async def screen(topics: Sequence[TrendItem], cfg: Config,
                 llm: StructuredCall | None) -> dict[int, Verdict]:
    """Screen every topic once. Returns exactly one `Verdict` per input topic, keys 1..N.

    The mapping is ALWAYS total: a missing, duplicated or out-of-range ordinal in the model's
    answer is logged and that ordinal defaults to `keep`, because an absent verdict is not a
    verdict and the caller must never have to ask whether a topic was screened.

    Args:
        topics: this run's topic items, in the order the console and the ref labels number them.
        cfg: the run config — `branding.competitors` is layer 1, `branding.profiles` supplies the
            product nouns the strip guards protect.
        llm: `llm.structured_call` (`models.StructuredCall`), or None for a $0 blocklist-only
            screen (the `--preview-sources` path, FR-139).
    """
    verdicts = {ordinal: Verdict(ordinal=ordinal) for ordinal in range(1, len(topics) + 1)}
    if not topics:
        return verdicts
    competitors = [term for term in cfg.branding.competitors if term and term.strip()]
    candidates = {ordinal: _candidates(topic) for ordinal, topic in enumerate(topics, 1)}
    for ordinal, topic in enumerate(topics, 1):
        if hits := _blocklist_hits(topic, candidates[ordinal], competitors):
            verdict = verdicts[ordinal]
            verdict.verdict = _STRIP
            verdict.brands_to_strip = hits[:_MAX_STRIPS]
            verdict.reason = f"blocklist: {', '.join(hits[:_MAX_STRIPS])}"

    cause = ""
    answers: list[Mapping[str, Any]] = []
    if llm is None:
        cause = "no model call available"
    else:
        try:
            answers = await _llm_verdicts(topics, cfg, llm)
        except _FilterUnavailable as exc:
            cause = str(exc)
        except Exception as exc:  # noqa: BLE001 — fail-open by contract (§1.5): a screen we could
            # not run must never cost the batch. The class NAME only — a provider error body can
            # carry a URL or a payload and this string reaches the operator (D30).
            cause = f"the classify call raised {type(exc).__name__}"
            logger.warning("topic_filter: screen call failed (%s)", type(exc).__name__)
    if cause:
        logger.warning("topic_filter: LLM layer degraded — %s; blocklist verdicts stand", cause)
        for verdict in verdicts.values():  # the marker the caller turns into ONE warning
            verdict.reason = f"filter_degraded: {cause}"
        return verdicts
    _merge(verdicts, answers, topics, candidates, cfg)
    return verdicts


def apply_blocklist(text: str, competitors: Sequence[str]) -> str:
    """`text` with every competitor string removed — word-boundary, case-insensitive, pure.

    The whitespace a removal leaves behind is collapsed (horizontal runs only: a caption's line
    breaks are part of its shape). Text that matched nothing is returned untouched, so this is
    safe to run over strings that must stay byte-identical when there is nothing to strip — which
    is the whole verbatim contract (§1.7).
    """
    if not text or not competitors:
        return text
    out = text
    for term in competitors:
        if term and (term := term.strip()):
            out = _pattern(term).sub("", out)
    if out == text:
        return text
    out = re.sub(r"[^\S\n]{2,}", " ", out)
    return "\n".join(line.strip() for line in out.split("\n")).strip()


# --------------------------------------------------------------------------------------------
# Layer 1 — the deterministic blocklist
# --------------------------------------------------------------------------------------------


@functools.lru_cache(maxsize=256)
def _pattern(term: str) -> re.Pattern[str]:
    """Word-boundary matcher for one term. Lookarounds rather than `\\b`, so a brand ending in a
    non-word character (`Acme+`, `C4`) still matches at its own edges."""
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)


def _candidates(topic: TrendItem) -> list[str]:
    """Every source string this topic could put on a creative — the strip guards' universe.

    Post-pivot the offerable strings are the `SourcePost` fields the copy call numbers (§1.7).
    The topic-level lists are included too: they still reach a prompt through `{{trend_texts}}`,
    and layer 1 is fail-closed, so a competitor's name sitting in one of them has to be seen.
    """
    out: list[str] = []
    for post in topic.posts:
        out.extend([post.caption, post.description, *post.hooks, *post.text_overlays,
                    *post.panel_texts])
    out.extend([*topic.hook_texts, *topic.text_overlay_contents, *topic.panel_texts])
    return [text for text in (str(item).strip() for item in out) if text]


def _blocklist_hits(topic: TrendItem, candidates: Sequence[str],
                    competitors: Sequence[str]) -> list[str]:
    """Which configured competitors this topic actually mentions, in config order."""
    haystacks = [topic.name, *candidates]
    return [term.strip() for term in competitors
            if any(_pattern(term.strip()).search(text) for text in haystacks)]


# --------------------------------------------------------------------------------------------
# Layer 2 — the batched classify call
# --------------------------------------------------------------------------------------------


async def _llm_verdicts(topics: Sequence[TrendItem], cfg: Config,
                        llm: StructuredCall) -> list[Mapping[str, Any]]:
    """One call, one answer list. Raises `_FilterUnavailable` on anything that is not usable."""
    system = _system_prompt(topics, cfg)
    result = await llm(
        _FILTER_ROLE,
        [{"role": "system", "content": system}, {"role": "user", "content": _CARRIER_TURN}],
        _answer_schema(),
        None,
    )
    if result.degraded:
        raise _FilterUnavailable(f"the classify call degraded ({result.reason or 'no reason'})")
    if not isinstance(result.parsed, Mapping):
        raise _FilterUnavailable("the answer was not a JSON object")
    if not isinstance(rows := result.parsed.get("verdicts"), list):
        raise _FilterUnavailable("the answer carried no `verdicts` list")
    return [row for row in rows if isinstance(row, Mapping)]


def _system_prompt(topics: Sequence[TrendItem], cfg: Config) -> str:
    """The rendered `topic_filter_system.md`: the fenced, engine-numbered topic list plus the
    competitor list.

    Wired at W2 exactly as the W1 stub described (contracts items 1 and 3): the engine assigns the
    ordinals — this module never numbers the topics itself, so the integer in a `Verdict` and the
    integer the model was shown come from one enumeration — and the two placeholders resolve for
    this role and for no other.

    The engine is built the way `runner._session` builds it, honouring the FR-174 `prompts_dir`
    override so an operator editing the screen's prompt gets the same seam as every other template.
    It is built per call rather than passed in because `screen()`'s signature is pinned to
    `(topics, cfg, llm)` and templates are hot-loaded per run anyway (FR-181); a filter call
    happens once a run.

    Every failure here — a missing placeholder, a template that names an out-of-role slot, an
    unreadable prompts directory — becomes `_FilterUnavailable`, which means the LLM layer degrades
    fail-open and the deterministic blocklist still runs. A screen we could not render is never a
    reason to lose the batch, and it is never a reason to send a half-built prompt to a metered
    model either.
    """
    try:
        engine = PromptEngine(override_dirs=[cfg.prompts_dir] if cfg.prompts_dir else [])
        context = build_context(topic_items=topics,
                                competitor_strings=tuple(cfg.branding.competitors))
        return engine.render(_TEMPLATE, context)
    except Exception as exc:  # noqa: BLE001 — assembly is fail-open by contract (§1.5)
        # The message is carried through, unlike the provider-side catch in `screen()`: prompt
        # assembly never touches a key, a header or an environment (FR-261 is structural), so the
        # worst thing in here is a template path and a placeholder name — which is exactly what
        # the operator needs to fix it. D30's redaction concern is about payloads, not paths.
        raise _FilterUnavailable(
            f"the filter prompt could not be assembled ({type(exc).__name__}: {exc})") from exc


def _answer_schema() -> dict[str, Any]:
    """The wire shape (§1.5). Hand-built rather than generated from a dataclass: `Verdict` is this
    module's own result type, and the answer is a list of rows the engine still has to police."""
    row = {
        "type": "object",
        "properties": {
            "ordinal": {"type": "integer"},
            "verdict": {"type": "string", "enum": [_KEEP, _STRIP, _SKIP]},
            "brands_to_strip": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
        "required": ["ordinal", "verdict", "brands_to_strip", "reason"],
        "additionalProperties": False,
    }
    return {
        "name": "topic_verdicts",
        "schema": {"type": "object", "properties": {"verdicts": {"type": "array", "items": row}},
                   "required": ["verdicts"], "additionalProperties": False},
    }


# --------------------------------------------------------------------------------------------
# Merge — ordinal policing, M15 strip guards, precedence
# --------------------------------------------------------------------------------------------


def _merge(verdicts: dict[int, Verdict], answers: Sequence[Mapping[str, Any]],
           topics: Sequence[TrendItem], candidates: Mapping[int, Sequence[str]],
           cfg: Config) -> None:
    """Fold the model's rows into the blocklist verdicts, in place."""
    rows: dict[int, list[Mapping[str, Any]]] = {}
    for row in answers:
        ordinal = _ordinal(row.get("ordinal"))
        if ordinal is None or ordinal not in verdicts:
            logger.warning("topic_filter: verdict for unknown ordinal %r ignored — that topic "
                           "defaults to keep", row.get("ordinal"))
            continue
        rows.setdefault(ordinal, []).append(row)
    if missing := sorted(set(verdicts) - set(rows)):
        logger.warning("topic_filter: no verdict returned for ordinal(s) %s — they default to keep",
                       ", ".join(str(item) for item in missing))
    for ordinal, group in rows.items():
        if len(group) > 1:
            logger.warning("topic_filter: %d verdicts returned for ordinal %d — none is "
                           "authoritative, so it defaults to keep", len(group), ordinal)
            continue
        _apply(verdicts[ordinal], group[0], topics[ordinal - 1], candidates[ordinal], cfg)


def _apply(current: Verdict, row: Mapping[str, Any], topic: TrendItem,
           candidates: Sequence[str], cfg: Config) -> None:
    """One model row onto one Verdict: guards first, then the stronger verdict wins."""
    answer = str(row.get("verdict") or _KEEP).strip().lower()
    if answer not in _RANK:
        logger.warning("topic_filter: ordinal %d returned verdict %r — defaulting to keep",
                       current.ordinal, row.get("verdict"))
        answer = _KEEP
    brands = _guarded(_strings(row.get("brands_to_strip")), topic, candidates, cfg)
    merged = _dedup([*current.brands_to_strip, *brands])[:_MAX_STRIPS]
    stands = _RANK[answer] >= _RANK[current.verdict]  # did the model's verdict survive layer 1?
    final = answer if stands else current.verdict
    if final == _STRIP and not merged:  # a strip with nothing left to strip is a keep
        final = _KEEP
    current.verdict = final
    current.brands_to_strip = merged if final != _KEEP else []
    # The blocklist's own reason is preserved when the model's verdict did NOT stand: "strip"
    # explained by a keep's reasoning would tell the operator the opposite of what happened.
    if (reason := str(row.get("reason") or "").strip()) and (stands or not current.reason):
        current.reason = reason


def _guarded(brands: Sequence[str], topic: TrendItem, candidates: Sequence[str],
             cfg: Config) -> list[str]:
    """The M15 strip guards — brand-as-subject protection, fail-safe.

    A rejected entry is logged and DROPPED; the verdict itself stands (`_apply` degrades a strip
    that empties). The candidate-length guard only judges strings the removal would actually
    change: an untouched short hook says nothing about whether this brand is strippable.
    """
    name = topic.name.lower()
    nouns = {noun.lower() for noun in _product_nouns(cfg)}
    kept: list[str] = []
    for raw in brands:
        brand = raw.strip()
        why = ""
        if len(brand) < _MIN_BRAND_CHARS:
            why = "shorter than three characters"
        elif brand.lower() in _STOPWORDS:
            why = "a common word, not a brand"
        elif brand.lower() in nouns:
            why = "one of OUR product names"
        elif brand.lower() in name:
            why = "part of the topic name — the brand is the subject here"
        elif _guts_a_candidate(brand, candidates):
            why = "removing it would leave a source string too short to mean anything"
        if why:
            logger.info("topic_filter: ignoring strip %r on topic %r — %s", brand, topic.name, why)
            continue
        kept.append(brand)
        if len(kept) >= _MAX_STRIPS:
            break
    return kept


def _guts_a_candidate(brand: str, candidates: Sequence[str]) -> bool:
    """Would removing `brand` leave a string it actually appears in too short to say anything?

    Only affected strings count. Judging untouched candidates would let one short hook elsewhere
    in the topic veto every strip, which is the opposite of what the guard is for.
    """
    for text in candidates:
        stripped = apply_blocklist(text, [brand])
        if stripped != text and len(stripped) < _MIN_CANDIDATE_CHARS:
            return True
    return False


def _product_nouns(cfg: Config) -> list[str]:
    """The active brand profile's product nouns — never strippable (they are ours, M15)."""
    profile = cfg.branding.profiles.get(cfg.branding.brand)
    return list(profile.product_nouns) if profile else []


def _ordinal(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _strings(value: Any) -> list[str]:
    if isinstance(value, (str, bytes)):
        return [str(value)]
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item).strip()]
    return []


def _dedup(values: Sequence[str]) -> list[str]:
    """First occurrence wins, case-insensitively — blocklist hits before model suggestions."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value.lower() not in seen:
            seen.add(value.lower())
            out.append(value)
    return out


__all__ = ["Verdict", "apply_blocklist", "screen"]
