"""FR-293 — one monitor becomes up to nine TOPICS, and every topic owns its own posts.

This file replaces `test_virlo_refs.py`, whose whole subject (reference sets, motion tiers, CDN
downloads) was withdrawn with the pivot: Virlo is a text-only source now (D41/D42), so the thing
worth pinning is no longer *which pictures a trend attaches* but **which posts a topic owns, in
what order, and what that ownership makes true**.

Four properties carry the split, and each is the one an implementation would plausibly get wrong:

1. **Cardinality is bounded and never shrinks.** `sources.virlo_topics_per_monitor` caps the
   themes consumed, `-1` is the kill switch (one item per monitor, the pre-pivot shape) and a
   monitor that named no theme still yields exactly one topic. A split that returned zero items
   for a theme-less monitor would silently drop a monitor the operator paid to watch.
2. **Allocation is EXCLUSIVE.** No post belongs to two topics of one monitor. That is what makes
   two topics carry different views, different engagement and therefore different STRENGTHS —
   nine copies of one monitor-wide number would make the whole ranking table a decoration, and
   §1.6 names that assertion explicitly.
3. **Extraction is a field MAP, never a rewrite.** `_source_post`'s docstring states the table;
   this suite reads that table out of the docstring and checks the code against it, so the
   documentation cannot drift from the mapping the copy call resolves its references back into.
4. **The funnel and the forensics reconcile.** Posts in, topics out, duplicates dropped and the
   filter verdicts are counted ONCE per monitor (the two-level `absorb` seam), and FR-298's three
   events say which posts exactly, which fields were read, and how the ranking was computed.

Everything is offline: the real captured corpus (`tests/fixtures/virlo/`) runs through the real
wrapper normalizers, the MCP session is a recorder, and nothing opens a socket, spawns a
subprocess, reads an API key or writes outside `tmp_path`. `sources/virlo.py` is imported directly
rather than through the `hypesocials.sources` facade because the facade's only entry point opens a
`SessionPool`; the mechanism under test is pure normalization behind it.
"""

from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from hypesocials.config import Config
from hypesocials.models import SourcePost, TrendItem
from hypesocials.sources import virlo
from hypesocials.virlo_mcp import server as virlo_server

FIXTURES = Path(__file__).parent / "fixtures" / "virlo"

#: The monitor the captured corpus belongs to, and the one `configs/hypedigitaly.yaml` ships.
MONITOR = "9c96fddf-dc35-4be0-bbd9-12f4d22aea12"


# --------------------------------------------------------------------------- fixtures & doubles


class _Log:
    """The `LogWriter` surface the adapter touches, and nothing else (module-local, house style).

    `event()` keeps the keyword payload whole — `verbose_only` included — because FR-298's whole
    point is WHICH surface a record lands on: `topic_ranked` is FR-5's ranked list and belongs in
    run.log, while `topic_posts` and `virlo_fields` are forensic and must not flood it.
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.warnings: list[tuple[str, str, dict[str, Any]]] = []

    # Positional-only, because the adapter passes `name=` and `trend=` as DATA keywords on
    # `virlo_payload`; a recorder whose own parameter is called `name` would collide with the
    # payload it exists to record.
    def event(self, event: str, message: str = "", /, **data: Any) -> None:
        self.events.append((event, message, data))

    def warn(self, event: str, message: str = "", /, **data: Any) -> None:
        self.warnings.append((event, message, data))

    def named(self, name: str) -> list[dict[str, Any]]:
        return [data for event, _message, data in self.events if event == name]

    def messages(self, name: str) -> list[str]:
        return [message for event, message, _data in self.events if event == name]

    def warned(self, name: str) -> list[str]:
        return [message for event, message, _ in self.warnings if event == name]


class _Session:
    """One MCP session: records every `(tool, args)` and answers from a canned payload map."""

    def __init__(self, payloads: dict[str, Any]) -> None:
        self._payloads = payloads
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool: str, args: dict[str, Any]) -> Any:
        self.calls.append((tool, dict(args)))
        return self._payloads.get(tool, {})


class _Pool:
    """`SessionPool`'s whole surface as far as `_monitor_item` is concerned."""

    def __init__(self, session: _Session) -> None:
        self.session = session

    @asynccontextmanager
    async def acquire(self) -> Any:
        yield self.session


def _body(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _corpus() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The real captured page, through the real wrapper normalizers: `(videos, slideshows)`."""
    videos = [virlo_server._norm_video(row)
              for row in _body("videos_views_desc_limit100.json")["data"]["videos"]]
    shows = [virlo_server._norm_slideshow(row)
             for row in _body("slideshows_views_desc_limit100.json")["data"]["slideshows"]]
    return videos, shows


def _corpus_analysis() -> dict[str, Any]:
    """`get_monitor_analysis`'s answer for the captured monitor, assembled the way the tool does.

    The tool itself is an async HTTP call, so its pure mapping is mirrored here and its per-theme
    normalizer (`_norm_theme`) is REUSED — which is also what keeps the fixture honest about the
    field the split would love to have: `_norm_theme` keeps five keys and `evidence_video_ids` is
    not among them, so `_allocate`'s evidence pass really does recover nothing today.
    """
    agent = _body("agent_detail.json")["data"]
    data = agent.get("analysis_data") or {}
    timing = data.get("timing_analysis") or {}
    return {
        "monitor_id": agent.get("id"),
        "name": agent.get("name"),
        "why_it_works": agent.get("analysis"),
        "themes": [virlo_server._norm_theme(theme) for theme in data.get("themes") or []],
        "viral_tactics": data.get("viral_tactics") or [],
        "key_highlight": data.get("key_highlight"),
        "connecting_thread": data.get("connecting_thread"),
        "timing_pattern": timing.get("pattern"),
        "peak_hours": timing.get("peak_hours") or [],
    }


def _config(**sources_kwargs: Any) -> Config:
    """A default `Config`; only `sources.*` matters here (`tests/test_plan.py:19`'s pattern)."""
    cfg = Config()
    for key, value in sources_kwargs.items():
        setattr(cfg.sources, key, value)
    return cfg


def _analysis(*themes: dict[str, Any], name: str = "AI Trends Tracker",
              **overrides: Any) -> dict[str, Any]:
    """A hand-built monitor analysis — used where the corpus's nine real themes are too coarse."""
    payload: dict[str, Any] = {
        "name": name,
        "why_it_works": "pattern interrupt in the first frame",
        "themes": list(themes),
        "viral_tactics": ["show the terminal"],
        "timing_pattern": "weekday mornings",
    }
    payload.update(overrides)
    return payload


def _theme(name: str, **overrides: Any) -> dict[str, Any]:
    theme = {"name": name, "why_it_works": f"{name} works because it proves something",
             "tactics": [f"{name} tactic"], "confidence": 0.8}
    theme.update(overrides)
    return theme


def _video(slug: str, *, views: int, post_id: str | None = None, author: str = "@creator",
           **overrides: Any) -> dict[str, Any]:
    """One `get_top_videos` row in `_norm_video`'s shape."""
    row = {
        "id": slug if post_id is None else post_id,
        "url": f"https://www.tiktok.com/@{author.lstrip('@')}/video/{slug}",
        "description": f"{slug} caption",
        "views": views, "likes": views // 20, "shares": views // 100,
        "comments": views // 200, "bookmarks": views // 300,
        "author_username": author,
        "publish_date": "2026-08-08T09:00:00Z",
        "hashtags": [f"#{slug}"],
        "hook_text": f"{slug} hook",
        "text_overlay_content": f"{slug} overlay",
        "summary": f"{slug} summary",
        "intelligence_status": "ready",
    }
    row.update(overrides)
    return row


def _slideshow(slug: str, *, views: int, panels: int = 3, post_id: str | None = None,
               author: str = "@deckmaker", **overrides: Any) -> dict[str, Any]:
    """One `get_top_slideshows` row in `_norm_slideshow`'s shape."""
    row = {
        "id": slug if post_id is None else post_id,
        "url": f"https://virlo.test/p/{slug}",
        "description": f"{slug} caption",
        "views": views, "likes": views // 20, "shares": views // 100,
        "comments": views // 200, "bookmarks": views // 300,
        "author_username": author,
        "publish_date": "2026-08-07T09:00:00Z",
        "hashtags": [f"#{slug}"],
        "image_urls": [f"https://cdn.virlo.test/{slug}-{n}.jpg" for n in range(1, panels + 1)],
        "panel_count": panels,
        "panel_texts": [f"{slug} panel {n}" for n in range(1, panels + 1)],
        "hook_text": f"{slug} hook",
        "summary": f"{slug} summary",
        "intelligence_status": "ready",
    }
    row.update(overrides)
    return row


def _split(analysis: dict[str, Any], videos: list[dict[str, Any]],
           shows: list[dict[str, Any]], *, cfg: Config | None = None,
           log: _Log | None = None, counters: virlo.Counters | None = None) -> list[TrendItem]:
    """One monitor's topics — the unit under test, no I/O of any kind."""
    return virlo._split_topics(MONITOR, analysis, videos, shows, cfg or _config(),
                               log=log, counters=counters)


def _post_ids(item: TrendItem) -> list[str]:
    return [post.post_id for post in item.posts]


# --------------------------------------------------------------------------- `_themes()` contract


def test_the_cap_bounds_how_many_themes_become_topics_and_the_keys_are_stable_slugs() -> None:
    """`sources.virlo_topics_per_monitor` is the ONE number that governs (it replaced
    `_MAX_THEMES = 3` in both of that constant's roles), and it bounds the filter call's worst
    case as well — `len(monitors) x cap` topics, priced pre-Collect."""
    themes = [_theme(f"theme number {index}") for index in range(12)]

    seeds = virlo._themes(_analysis(*themes), cap=9)

    assert len(seeds) == 9
    assert [seed.name for seed in seeds] == [theme["name"] for theme in themes[:9]]
    assert seeds[0].key == "theme-number-0"
    # Uncapped slug: the same theme name yields the same key run after run, which is the whole
    # point of a key that ends up inside `history_key`.
    long_name = "a theme name that is considerably longer than any slug cap would allow it to be"
    assert virlo._themes(_analysis(_theme(long_name)), cap=9)[0].key == (
        "a-theme-name-that-is-considerably-longer-than-any-slug-cap-would-allow-it-to-be")


def test_the_minus_one_kill_switch_returns_one_item_carrying_the_pre_pivot_history_key() -> None:
    """`-1` is the only way to un-ship the split without a code change, so it has to produce the
    PRE-PIVOT item exactly: one topic per monitor, keyed on the bare monitor id, so an existing
    `trend_history.json` window keeps matching."""
    themes = [_theme("first theme"), _theme("second theme")]
    cfg = _config(virlo_topics_per_monitor=-1)

    seeds = virlo._themes(_analysis(*themes), cap=virlo._topic_cap(cfg))
    items = _split(_analysis(*themes), [_video("v1", views=900)], [], cfg=cfg)

    assert [seed.key for seed in seeds] == [""]
    assert len(items) == 1
    assert items[0].history_key == MONITOR and "::" not in items[0].history_key
    assert items[0].topic_key == ""
    assert items[0].name == "AI Trends Tracker", "the aggregate is named after the MONITOR"


def test_a_monitor_that_named_no_theme_still_yields_exactly_one_synthesized_topic() -> None:
    """"never fewer items than the pre-pivot adapter did" — a theme-less monitor is a monitor the
    operator configured and paid for, so it must not vanish because Virlo's analysis was thin."""
    for analysis in (_analysis(), _analysis(_theme(""), _theme("   ")), {"name": "bare"}):
        items = _split(analysis, [_video("v1", views=10)], [])

        assert len(items) == 1
        assert items[0].topic_key == ""
        assert items[0].history_key == MONITOR
        assert len(items[0].posts) == 1, "the single topic still owns every post"


def test_a_theme_backed_topic_is_keyed_monitor_then_topic_and_collisions_take_a_suffix() -> None:
    """`history_key = "<mid>::<topic_key>"` (§1.6). The monitor id LEADS because Virlo's theme
    names collide ACROSS monitors, and a duplicate key inside one monitor takes `#2` — the
    runner and previews build `{history_key: topic}` maps, so a collision would DROP a topic
    silently rather than report one.
    """
    analysis = _analysis(_theme("agent demos"), _theme("agent demos"), _theme("agent  demos"))

    items = _split(analysis, [_video("v1", views=10)], [])

    assert [item.topic_key for item in items] == ["agent-demos", "agent-demos#2", "agent-demos#3"]
    assert [item.history_key for item in items] == [f"{MONITOR}::{key}" for key in
                                                    ("agent-demos", "agent-demos#2",
                                                     "agent-demos#3")]
    assert len(set(item.history_key for item in items)) == 3


def test_the_real_corpus_monitor_splits_into_its_nine_themes_at_the_default_cap() -> None:
    """The end-to-end cardinality claim on real captured data: nine themes, nine topics, nine
    distinct history keys, and the whole page of posts dealt out among them."""
    videos, shows = _corpus()

    items = _split(_corpus_analysis(), videos, shows)

    assert len(items) == 9 == _config().sources.virlo_topics_per_monitor
    assert len({item.history_key for item in items}) == 9
    assert all(item.history_key.startswith(f"{MONITOR}::") for item in items)
    assert sum(len(item.posts) for item in items) == len(virlo._dedupe(videos)) + len(
        virlo._dedupe(shows))


# --------------------------------------------------------------- `SourcePost` extraction map


#: `SourcePost` attribute -> the Virlo row key it is read from, as `_source_post`'s docstring
#: states it. Parsed from the docstring rather than retyped, so the table an implementer reads and
#: the mapping the copy call resolves references back into cannot drift apart (§1.7).
def _documented_field_map() -> dict[str, str]:
    rows = {}
    for line in (virlo._source_post.__doc__ or "").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not cells[0].startswith("`"):
            continue
        attribute, source = cells[0].strip("` "), cells[1].strip("` *")
        # Skip the header row, its `---` rule, and the identity row (four fields, one cell).
        if attribute.startswith("-") or "/" in attribute or attribute == "SourcePost":
            continue
        rows[attribute] = source
    return rows


def test_the_documented_field_map_is_the_one_the_code_actually_applies() -> None:
    """Every row of `_source_post`'s table, checked with a distinct marker per Virlo field.

    This is the assertion that stops the two most expensive quiet mistakes: `caption` reading
    Virlo's `summary` (an AI paraphrase shipped as the creator's own words) and `description`
    reading the creator's caption (the field the on-image pre-filter is entitled to refuse).
    """
    documented = _documented_field_map()
    assert documented == {"caption": "description", "hooks": "hook_text",
                          "text_overlays": "text_overlay_content", "panel_texts": "panel_texts",
                          "description": "summary"}, documented
    raw = {"id": "p-1", "url": "https://virlo.test/p/1", "author_username": "@writer",
           "description": "MARKER-CREATOR-CAPTION", "summary": "MARKER-VIRLO-SUMMARY",
           "hook_text": "MARKER-HOOK", "text_overlay_content": "MARKER-OVERLAY",
           "panel_texts": ["MARKER-PANEL-1", "MARKER-PANEL-2"],
           "views": 4_900_000, "publish_date": "2026-08-08T09:00:00Z"}

    post = virlo._source_post(raw, MONITOR, 0, is_slideshow=True)

    # `hooks` and `text_overlays` are LISTS on `SourcePost` fed by a SCALAR Virlo field (a row
    # carries one of each), so the documented mapping lands as a one-element list; `panel_texts`
    # is a list on both sides and the two scalars stay scalars.
    wrapped = {"hooks", "text_overlays"}
    for attribute, source in documented.items():
        expected = raw[source]
        assert getattr(post, attribute) == ([expected] if attribute in wrapped else expected), \
            attribute
    assert post.caption == "MARKER-CREATOR-CAPTION" and post.description == "MARKER-VIRLO-SUMMARY"
    assert post.hooks == ["MARKER-HOOK"] and post.text_overlays == ["MARKER-OVERLAY"]
    assert (post.post_id, post.url, post.author) == ("p-1", "https://virlo.test/p/1", "@writer")
    assert post.views == 4_900_000 and post.is_slideshow is True
    assert post.published_at is not None and post.published_at.year == 2026


def test_a_source_string_is_stored_exactly_as_it_arrived_diacritics_and_emoji_included() -> None:
    """D42's whole basis: the copy call selects these strings BY REFERENCE and the engine resolves
    the reference back to these bytes, so a string edited on the way IN can no longer be quoted
    verbatim on the way OUT. Only the outer whitespace goes."""
    text = "  Nejrychlejší způsob, jak 🚀 zvýšit obrat — bez agentury  "
    raw = {"id": "p-1", "description": text, "hook_text": text, "summary": text,
           "panel_texts": [text], "views": 1}

    post = virlo._source_post(raw, MONITOR, 0, is_slideshow=False)

    assert post.caption == text.strip()
    assert post.hooks == [text.strip()]
    assert "Nejrychlejší" in post.caption and "🚀" in post.caption and "—" in post.caption
    assert post.panel_texts == [text], "panel texts keep their own spacing — they are slide bytes"


def test_a_row_with_neither_id_nor_url_takes_a_stable_positional_post_id() -> None:
    """`_post_id` must never fall back to `id(row)`: an id that differs on every run would grow
    `trend_history.json` forever while freshness silently stopped working."""
    first = virlo._source_post({"views": 5}, MONITOR, 4, is_slideshow=True)
    second = virlo._source_post({"views": 5}, MONITOR, 4, is_slideshow=True)

    assert first.post_id == second.post_id == f"{MONITOR}:4"
    assert not any(part.isdigit() and len(part) > 8 for part in first.post_id.split(":")[1:])


# ------------------------------------------------------------------ ranking and exclusive shares


def test_every_topics_posts_are_view_ranked_because_the_labels_count_over_that_order() -> None:
    """`P<n>` in a copy prompt means "the n-th ranked post of this topic" (§1.7), and FR-297b
    prints the same order as the sort proof — so the ordering is a contract, not a convenience.
    Both media arrays arrive independently sorted, so this is the one place the merge happens."""
    videos = [_video("v-mid", views=500_000), _video("v-low", views=1_000)]
    shows = [_slideshow("s-top", views=5_000_000), _slideshow("s-low", views=2_000)]

    item = _split(_analysis(), videos, shows)[0]

    assert _post_ids(item) == ["s-top", "v-mid", "s-low", "v-low"]
    assert [post.views for post in item.posts] == sorted(
        [post.views for post in item.posts], reverse=True)
    assert item.posts[0].views == 5_000_000, "a slideshow may lead a video-heavy monitor"


def test_no_post_belongs_to_two_topics_and_the_shares_reconcile_with_posts_in() -> None:
    """Exclusivity IS the split (FR-293). Overlapping shares would give every topic the monitor's
    strongest post, which is how nine topics end up quoting the same caption nine times."""
    videos = [_video(f"v{index}", views=100_000 - index) for index in range(11)]
    counters = virlo.Counters()

    items = _split(_analysis(_theme("one"), _theme("two"), _theme("three")), videos, [],
                   counters=counters)

    shares = [set(_post_ids(item)) for item in items]
    assert len(items) == 3
    assert set().union(*shares) == {f"v{index}" for index in range(11)}
    assert sum(len(share) for share in shares) == 11, "a post dealt twice would show up here"
    for index, share in enumerate(shares):
        for other in shares[index + 1:]:
            assert not share & other
    assert (counters.posts_in, counters.topics_out) == (11, 3)


def test_a_single_seed_takes_every_row_because_there_is_nothing_to_divide() -> None:
    videos = [_video(f"v{index}", views=10 - index) for index in range(4)]

    items = _split(_analysis(_theme("only theme")), videos, [])

    assert len(items) == 1
    assert _post_ids(items[0]) == ["v0", "v1", "v2", "v3"]


def test_two_topics_of_one_monitor_carry_different_post_sets_and_different_strengths() -> None:
    """THE assertion §1.6 names, and the reason the split exists at all.

    A monitor-wide figure repeated across every topic would rank them identically and make the
    ranking table a decoration; the shares here differ by an order of magnitude in views, so a
    strength that ignored the share would come back equal.
    """
    videos = [_video("huge", views=20_000_000), _video("tiny", views=1_000)]

    items = _split(_analysis(_theme("first"), _theme("second")), videos, [])
    virlo._score(items)  # min-max needs the whole pool, so scoring is the caller's step

    assert [_post_ids(item) for item in items] == [["huge"], ["tiny"]]
    assert items[0].total_views == 20_000_000 and items[1].total_views == 1_000
    assert items[0].strength != items[1].strength
    assert items[0].strength > items[1].strength
    assert items[0].engagement["likes"] != items[1].engagement["likes"]


def test_every_ranked_quantity_of_a_topic_is_measured_over_its_own_posts() -> None:
    """Views, median, engagement and the raw velocity component all come from the topic's share —
    checked against arithmetic done here rather than against a second call of the same helper."""
    videos = [_video("a", views=1_000), _video("b", views=3_000), _video("c", views=5_000)]

    items = _split(_analysis(_theme("first"), _theme("second")), videos, [])

    first, second = items
    assert _post_ids(first) == ["c", "a"] and _post_ids(second) == ["b"]
    assert first.total_views == 6_000 and second.total_views == 3_000
    assert first.median_views == 3_000 and second.median_views == 3_000
    assert first.engagement["likes"] == 5_000 // 20 + 1_000 // 20
    assert second.engagement["likes"] == 3_000 // 20
    assert set(first.strength_components) == set(virlo._WEIGHTS)


def test_the_strength_weights_are_the_prds_and_confidence_no_longer_weighs_the_rank() -> None:
    """FR-5, amended v2.0.0: total views .35, median .15, velocity .30, ENGAGEMENT .20 — the 0.20
    slot moved off Virlo's theme `confidence`, which stopped being a per-item discriminator once
    every topic of a monitor was one theme. Confidence is still populated and still logged."""
    assert virlo._WEIGHTS == {"total_views": 0.35, "median_views": 0.15,
                              "velocity": 0.30, "engagement": 0.20}
    assert round(sum(virlo._WEIGHTS.values()), 10) == 1.0
    assert "confidence" not in virlo._WEIGHTS

    # The confident theme is deliberately given the WEAKER post (the stride deal hands the
    # strongest row to the FIRST theme): under the pre-amendment weights its 0.20 confidence share
    # could still lift it, and here it must not.
    items = _split(_analysis(_theme("unsure", confidence=0.0), _theme("confident", confidence=1.0)),
                   [_video("tiny", views=1_000), _video("huge", views=20_000_000)], [])
    virlo._score(items)

    unsure, confident = items
    assert [unsure.confidence, confident.confidence] == [0.0, 1.0], "still populated for the log"
    assert [_post_ids(unsure), _post_ids(confident)] == [["huge"], ["tiny"]]
    assert set(confident.strength_components) == set(virlo._WEIGHTS)
    assert "confidence" not in confident.strength_components
    assert confident.strength < unsure.strength, "posts decide the rank, confidence does not"


def test_is_slideshow_is_a_strict_majority_over_the_topics_own_posts() -> None:
    """FR-90's carousel affinity, re-derived post-pivot. A tie reads as video, because the burden
    of proof sits on the rarer, more expensive-to-imitate format."""
    two_decks = _split(_analysis(), [_video("v", views=1)],
                       [_slideshow("s1", views=3), _slideshow("s2", views=2)])[0]
    tied = _split(_analysis(), [_video("v", views=3)], [_slideshow("s", views=2)])[0]
    video_heavy = _split(_analysis(), [_video("v1", views=3), _video("v2", views=2)],
                         [_slideshow("s", views=1)])[0]

    assert two_decks.is_slideshow is True
    assert tied.is_slideshow is False, "a 1-1 split is not a majority"
    assert video_heavy.is_slideshow is False


def test_a_monitor_that_shipped_no_post_still_yields_topics_and_says_so_once() -> None:
    """Not fatal and not silent: the topics still carry the analysis text and Select decides
    (FR-6). Silent, this reads downstream as "the trend was weak" rather than "the monitor shipped
    nothing", which is a different fix entirely."""
    log = _Log()

    items = _split(_analysis(_theme("first"), _theme("second")), [], [], log=log)

    assert len(items) == 2
    assert all(item.posts == [] for item in items)
    assert all(item.total_views == 0 and item.is_slideshow is False for item in items)
    assert len(log.warned("virlo_monitor_empty")) == 1


# --------------------------------------------------------------------------- the funnel (FR-155)


def test_one_monitors_rows_are_counted_once_and_never_once_per_topic() -> None:
    """The two-level `absorb` seam, which is the discipline that keeps the split honest: nine
    topics built from one monitor's 200 rows are 200 posts in, not 1,800. The defect it prevents
    is exactly the pre-FR-155 `virlo_payload` lie about duplicates, one level up."""
    videos = [_video(f"v{index}", views=100 - index) for index in range(9)]
    shows = [_slideshow("s1", views=50)]
    run_wide = virlo.Counters()

    tally = virlo.Counters()
    _split(_analysis(*[_theme(f"theme {index}") for index in range(3)]), videos, shows,
           counters=tally)
    run_wide.absorb(tally)

    assert (tally.posts_in, tally.topics_out) == (10, 3)
    assert (tally.videos_kept, tally.slideshows_kept) == (9, 1)
    assert run_wide.posts_in == 10, "absorbed once, not once per topic"
    assert run_wide.topics_out == 3
    assert run_wide.posts_kept == 10


def test_duplicates_dropped_is_an_explicit_field_that_both_construction_styles_agree_on() -> None:
    """Contracts item 15 promoted the old `raw - kept` view into a field. `__post_init__` still
    derives it for a tally stated in one shot, because a zero there would read as "nothing was
    repeated" — the precise false negative FR-155 exists to prevent."""
    repeated = [_video("v1", views=10), _video("v1", views=10), _video("v2", views=9)]
    tally = virlo.Counters()

    items = _split(_analysis(), repeated, [], counters=tally)

    assert tally.videos_raw == 3 and tally.videos_kept == 2
    assert tally.duplicates_dropped == 1
    assert tally.posts_in == 2, "the split reads the DEDUPED rows"
    assert _post_ids(items[0]) == ["v1", "v2"]
    one_shot = virlo.Counters(videos_raw=7, slideshows_raw=3, videos_kept=6, slideshows_kept=2)
    assert one_shot.duplicates_dropped == 2
    assert virlo.Counters(videos_kept=4).duplicates_dropped == 0, "never negative"


def test_record_filter_counts_the_three_verdicts_and_latches_the_degrade_marker() -> None:
    """FR-294's verdicts as `runner._screen_topics` receives them — duck-typed on `.verdict`/
    `.reason`, so the funnel never imports the filter and the filter never imports the funnel.
    An unrecognised verdict counts as `keep`, the filter module's own total-by-construction
    default, rather than a silent drop."""
    from hypesocials.topic_filter import Verdict

    counters = virlo.Counters()
    counters.record_filter({
        1: Verdict(1, "keep"),
        2: Verdict(2, "strip", ["AcmeCorp"]),
        3: Verdict(3, "skip", reason="sponsored launch post"),
        4: Verdict(4, ""),
    })

    assert (counters.filter_kept, counters.filter_stripped, counters.filter_skipped) == (2, 1, 1)
    assert counters.filter_degraded is False
    assert counters.as_event()["filter"] == {"kept": 2, "stripped": 1, "skipped": 1,
                                             "degraded": False}

    degraded = virlo.Counters()
    degraded.record_filter([Verdict(1, "keep", reason="filter_degraded: no llm configured")])
    assert degraded.filter_degraded is True
    assert degraded.filter_kept == 1

    run_wide = virlo.Counters()
    run_wide.absorb(counters)
    run_wide.absorb(degraded)
    assert run_wide.filter_kept == 3 and run_wide.filter_degraded is True, "a bool folds by OR"


def test_the_funnel_event_and_its_run_log_sentence_read_the_post_pivot_stages() -> None:
    """FR-155's machine record and the flat sentence beside it: the nested objects would render in
    run.log as a shredded dict, so the sentence is what an operator actually reads."""
    counters = virlo.Counters(monitors_asked=2, monitors_failed=1)
    counters.add_input(videos_raw=6, slideshows_raw=4, videos_kept=5, slideshows_kept=4,
                       total_available=2_039)
    counters.add_topics(posts_in=9, topics_out=3)
    counters.trends_returned = 3

    payload = counters.as_event()

    # W3 conductor decision (FR-296): `synthesized` joined the topics group so the TOPICS stage
    # header can print its `N synth` clause — a monitor-aggregate fallback is now countable.
    assert payload["topics"] == {"posts_in": 9, "topics_out": 3, "synthesized": 0, "returned": 3}
    assert payload["input"]["duplicates_dropped"] == 1
    assert payload["input"]["total_available"] == 2_039
    line = counters.summary_line()
    assert "9 post(s) after 1 duplicate(s)" in line
    assert "3 topic(s) from 1 monitor(s)" in line and "3 returned" in line


# --------------------------------------------------------------------- FR-298 forensic events


async def test_topic_posts_names_every_post_in_rank_order_and_stays_out_of_run_log() -> None:
    """"Which posts exactly" — the gap that made the `views desc` sort unverifiable from any
    surface. The `P<n>` ordinals in this record ARE §1.7's reference labels, so a rendered caption
    stays traceable to a real post afterwards without re-running anything.

    `verbose_only` because events.jsonl always receives it and run.log must stay readable;
    FR-297b prints the head of this same list to the console.
    """
    log = _Log()
    session = _Session({"get_monitor_analysis": _analysis(_theme("first"), _theme("second")),
                        "get_top_videos": {"videos": [_video("v-top", views=4_900_000),
                                                      _video("v-mid", views=900_000)],
                                           "total": 2_039},
                        "get_top_slideshows": {"slideshows": [_slideshow("s-low", views=1_000)],
                                               "total": 635}})

    items = await virlo._monitor_item(_Pool(session), MONITOR, _config(), log)

    records = log.named("topic_posts")
    assert len(records) == len(items) == 2
    assert all(record["verbose_only"] is True for record in records)
    for record, item in zip(records, items, strict=True):
        assert record["trend"] == item.history_key and record["topic"] == item.topic_key
        assert [row["post_id"] for row in record["posts"]] == _post_ids(item)
        assert [row["views"] for row in record["posts"]] == sorted(
            (row["views"] for row in record["posts"]), reverse=True)
        assert set(record["posts"][0]) == {"post_id", "url", "author", "views"}
    assert "P1 at 4,900,000 views" in log.messages("topic_posts")[0]


async def test_virlo_fields_is_the_per_monitor_consumption_ledger() -> None:
    """Three questions nobody could answer without a debugger: what Virlo sent, what was read, and
    what was ignored. The third is the interesting one — `evidence_video_ids` is dropped by the
    wrapper's `_norm_theme`, and until this event existed "a gap here" and "dead weight there"
    looked identical from outside."""
    log = _Log()
    videos, shows = _corpus()
    session = _Session({"get_monitor_analysis": _corpus_analysis(),
                        "get_top_videos": {"videos": videos, "total": 2_039},
                        "get_top_slideshows": {"slideshows": shows, "total": 635}})

    await virlo._monitor_item(_Pool(session), MONITOR, _config(), log)

    records = log.named("virlo_fields")
    assert len(records) == 1
    record = records[0]
    assert record["verbose_only"] is True
    assert record["monitor_id"] == MONITOR and record["topics"] == 9
    ledger = record["fields"]
    assert set(ledger) == {"analysis", "theme", "video", "slideshow"}
    for shape, entry in ledger.items():
        assert set(entry) == {"present", "consumed", "ignored"}, shape
        assert set(entry["consumed"]) <= set(entry["present"])
        assert not set(entry["consumed"]) & set(entry["ignored"])
    assert "views" in ledger["video"]["consumed"] and "hook_text" in ledger["video"]["consumed"]
    assert "panel_texts" in ledger["slideshow"]["consumed"]
    assert record["ignored"] == sorted(record["ignored"])
    assert "thumbnail_url" in record["ignored"], "the media fields really are ignored post-pivot"


def test_topic_ranked_carries_the_table_rows_with_raw_components_and_is_not_verbose_only() -> None:
    """FR-5 requires the full ranked list with each component in the RUN LOG, so unlike the other
    two forensic events this one is not verbose-only. Both halves travel because min-max is lossy
    in exactly the way that matters: `total_views: 1.0` says a topic led the pool, never whether
    it led by 3% or by 300x."""
    log = _Log()
    items = _split(_analysis(_theme("first"), _theme("second")),
                   [_video("huge", views=20_000_000), _video("tiny", views=1_000)], [])
    raw = {item.history_key: dict(item.strength_components) for item in items}
    virlo._score(items)
    items.sort(key=lambda item: item.strength, reverse=True)

    virlo._ranked_event(log, items, raw)

    records = log.named("topic_ranked")
    assert len(records) == 1
    assert "verbose_only" not in records[0], "FR-5's ranked list belongs in run.log"
    rows = records[0]["topics"]
    assert [row["rank"] for row in rows] == [1, 2]
    assert [row["topic_key"] for row in rows] == ["first", "second"]
    assert rows[0]["history_key"] == f"{MONITOR}::first"
    assert rows[0]["views"] == 20_000_000 and rows[0]["posts"] == 1
    assert set(rows[0]["components"]) == set(virlo._WEIGHTS)
    assert rows[0]["components_raw"]["total_views"] == 20_000_000.0
    assert rows[0]["components"]["total_views"] == 1.0, "normalized beside raw, not instead of it"
    assert rows[0]["strength"] > rows[1]["strength"]


async def test_the_per_topic_payload_reports_the_topics_own_posts_not_the_monitors_totals() -> None:
    """`virlo_payload` one level up: nine topics printing one monitor-wide "100 videos, 100
    slideshows" would be the same over-reporting defect the dedupe fix closed. The monitor-wide
    figures stay beside them in `data`, because a dedupe drop is a fact about the monitor and
    cannot be attributed to any one topic."""
    log = _Log()
    session = _Session({"get_monitor_analysis": _analysis(_theme("first"), _theme("second")),
                        "get_top_videos": {"videos": [_video("v1", views=10),
                                                      _video("v2", views=9)], "total": 40},
                        "get_top_slideshows": {"slideshows": [_slideshow("s1", views=8)],
                                               "total": 12}})

    items = await virlo._monitor_item(_Pool(session), MONITOR, _config(), log)

    payloads = log.named("virlo_payload")
    assert len(payloads) == 2
    assert sum(row["posts"] for row in payloads) == 3
    assert all(row["monitor_videos_kept"] == 2 for row in payloads)
    assert all(row["monitor_slideshows_kept"] == 1 for row in payloads)
    assert all(row["total_available"] == 52 for row in payloads)
    assert [row["topic"] for row in payloads] == [item.topic_key for item in items]
    assert payloads[0]["views"] == items[0].total_views


async def test_both_media_calls_still_ask_for_the_monitors_winners_after_the_split() -> None:
    """The sort is what makes `P1` mean anything, so the split must not have quietly dropped it:
    `views desc`, one page of 100, never an `offset` (Virlo answers that with HTTP 400)."""
    session = _Session({"get_monitor_analysis": _analysis(_theme("first"))})

    await virlo._monitor_item(_Pool(session), MONITOR, _config())

    media = {tool: args for tool, args in session.calls if tool != "get_monitor_analysis"}
    assert set(media) == {"get_top_videos", "get_top_slideshows"}
    for args in media.values():
        assert args == {"monitor_id": MONITOR, "limit": 100, "order_by": "views", "sort": "desc"}
    assert all("offset" not in args for _tool, args in session.calls)


# --------------------------------------------------------------------------- the public entry


async def test_fetch_with_no_monitor_ids_says_so_on_the_console_and_opens_no_session() -> None:
    """`fetch`'s public contract, and the one refusal an operator must not have to find in run.log.

    The short-circuit is what makes this test safe to run offline: it returns before `SessionPool`
    opens, so no MCP subprocess is spawned and no key is read.
    """
    said: list[str] = []
    log = _Log()

    feed = await virlo.fetch(_config(virlo_monitor_ids=[]), log=log, used_posts=None,
                             say=said.append)

    assert feed == []
    assert feed.counters.monitors_asked == 0
    assert len(said) == 1 and "virlo_monitor_ids" in said[0] and "--list-monitors" in said[0]
    assert log.warned("virlo_no_monitors")
    assert log.named("collect_funnel"), "the funnel is written even for an empty run"


def test_a_topic_reads_its_own_theme_while_the_aggregate_reads_the_monitor() -> None:
    """The two text sources stay distinct: a theme-backed topic carries the monitor's reading and
    then its own theme's, while the synthesized item carries the aggregate that spans every
    consumed theme — the pre-pivot item's text exactly."""
    analysis = _analysis(_theme("agent demos", why_it_works="proof over promise",
                                tactics=["show the terminal"]),
                         _theme("vibecoding", why_it_works="fast wins", tactics=["screen record"]))

    themed = _split(analysis, [_video("v", views=1)], [])
    aggregate = _split(analysis, [_video("v", views=1)], [],
                       cfg=_config(virlo_topics_per_monitor=-1))[0]

    assert "pattern interrupt in the first frame" in themed[0].why_it_works
    assert "agent demos: proof over promise" in themed[0].why_it_works
    assert "vibecoding" not in themed[0].why_it_works, "a topic never reads its sibling's theme"
    assert themed[0].tactics[0] == "show the terminal", "the theme's OWN tactics lead"
    assert "screen record" not in themed[0].tactics
    assert "agent demos: proof over promise" in aggregate.why_it_works
    assert "vibecoding: fast wins" in aggregate.why_it_works
    assert aggregate.confidence == pytest.approx(0.8)


def test_a_topics_hashtags_and_labels_come_from_its_own_posts_and_stay_capped() -> None:
    """A13/A14 at topic granularity: the intelligence labels and the winning posts' real hashtags
    are read off the topic's OWN share, deduped and capped, so one tag-spraying post cannot fill
    the list and a sibling topic's labels cannot leak in."""
    videos = [_video("a", views=30, hook_type="story_tease", hashtags=["#ai", "#AI", "#alpha"]),
              _video("b", views=20, hook_type="none", hashtags=["#beta"]),
              _video("c", views=10, hook_type="tutorial_promise", hashtags=["#gamma"])]

    items = _split(_analysis(_theme("first"), _theme("second")), videos, [])

    first, second = items
    assert _post_ids(first) == ["a", "c"] and _post_ids(second) == ["b"]
    assert first.hook_types == ["story_tease", "tutorial_promise"]
    assert second.hook_types == [], "`none` is an absence wearing a label (A13)"
    assert first.hashtags == ["#ai", "#alpha", "#gamma"] and second.hashtags == ["#beta"]
    assert len(first.hashtags) <= virlo._MAX_HASHTAGS


def test_the_slug_and_the_history_key_survive_a_theme_name_full_of_punctuation() -> None:
    """`history_key` ends up as a JSON object key in `trend_history.json`, so the slug has to be
    stable and printable whatever Virlo names a theme."""
    analysis = _analysis(_theme("Claude AI: Coding & Development (2026!)"))

    item = _split(analysis, [_video("v", views=1)], [])[0]

    assert re.fullmatch(r"[a-z0-9-]+", item.topic_key), item.topic_key
    assert item.history_key == f"{MONITOR}::{item.topic_key}"
    assert item.name == "Claude AI: Coding & Development (2026!)", "the NAME stays verbatim"
