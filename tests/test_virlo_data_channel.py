"""A2 / A13 / A14 — the data channel from Virlo's wire to the prompt that spends money.

Three claims are pinned here, in the order they change what gets rendered:

1. **A2 — the sort reaches the wire.** The adapter asks for `order_by=views&sort=desc&limit=100`
   on both media tools and never sends `offset`. Unsorted, this tool drew every reference it has
   ever attached from the bottom of a 2,039-row pool: measured 2026-08-11, a median of 2,534 views
   against 1,940,676 sorted. Post-pivot the stake is higher, not lower — post RANK now picks the
   verbatim copy (§1.7's `P<n>` labels count over exactly this order) — and a regression is still
   invisible in output, because the run succeeds on rubbish posts.
2. **A13 — Virlo's own labels survive** wrapper → adapter → prompt, view-ranked, absent-safe, and
   read PER ROW: the corpus monitor reports `data_intelligence_enabled: false` while 70 of its 100
   rows carry a populated `intelligence` block.
3. **A14 — the winning posts' real hashtags reach the copy prompt** as reference material, while
   the invented-from-slug fallback stays exactly what it was: the last resort, for its own case.

**A18's digest-exemplar tier is gone (v2.0.0).** The digest used to hand five `top_exemplars` per
trend to the adapter as a last-resort REFERENCE tier; post-pivot there is no reference tier at all
(the visuals come from the style registry, FR-290) and those posts are global rather than this
niche's, so offering their text would import off-niche copy into a topic that has its own. What
survives here is the seam: `_digest` returns a 2-TUPLE, and the wrapper still normalizes the
payload nothing reads.

Everything is offline. **No test here calls `/trends/digest`** — it is Virlo's only metered
endpoint ($0.25 a call), so the digest shapes are spelled out as literals and the sessions are
stubs; nothing opens a socket, spawns an MCP subprocess or reads `VIRLO_API_KEY`. Wherever a real
shape exists it comes from `tests/fixtures/virlo/`, whole, envelope included, so normalization runs
against rows with `intelligence: null`, absent hooks, bare and `#`-prefixed hashtags in one
response, and slideshows whose panels arrive as `{image_url, position}`.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from hypesocials import copywrite
from hypesocials.config import Config
from hypesocials.models import PlanEntry, TrendItem
from hypesocials.prompts_engine import PromptEngine, build_context
from hypesocials.sources import virlo
from hypesocials.virlo_mcp import server as virlo_server

FIXTURES = Path(__file__).parent / "fixtures" / "virlo"

#: The monitor the captured corpus belongs to, and the one `configs/hypedigitaly.yaml` ships.
MONITOR = "9c96fddf-dc35-4be0-bbd9-12f4d22aea12"

#: One digest group in Virlo's own raw shape. Written out rather than captured because
#: `/trends/digest` bills — see `tests/fixtures/virlo/README.md`.
DIGEST_BODY: dict[str, Any] = {
    "data": [{
        "id": "group-1", "title": "Global", "region": "global", "local_date": "2026-08-11",
        "trends": [
            {
                "ranking": 1, "trend": {"name": "AI agents", "description": "agents everywhere"},
                "global_confidence": 0.71, "momentum": {"status": "rising", "views_per_hour": 900},
                "exemplar_count": 2,
                "top_exemplars": [
                    {"video_id": "ex-weak", "url": "https://tiktok.test/p/ex-weak",
                     "platform": "tiktok", "views": 10_000,
                     "thumbnail_url": "https://cdn.virlo.test/digest-weak.jpg",
                     "publish_date": "2026-08-10T09:00:00Z",
                     "author": {"username": "@weak", "avatar_url": "a", "verified": False}},
                    {"video_id": "ex-strong", "url": "https://tiktok.test/p/ex-strong",
                     "platform": "tiktok", "views": 4_000_000,
                     "thumbnail_url": "https://cdn.virlo.test/digest-strong.jpg",
                     "publish_date": "2026-08-09T09:00:00Z",
                     "author": {"username": "@strong", "avatar_url": "b", "verified": True}},
                ],
            },
            {
                "ranking": 2, "trend": {"name": "Vibecoding"}, "global_confidence": None,
                "top_exemplars": [
                    {"video_id": "ex-lonely", "url": "https://tiktok.test/p/ex-lonely",
                     "platform": "youtube", "views": 5_000_000,
                     "thumbnail_url": "https://cdn.virlo.test/digest-lonely.jpg",
                     "publish_date": "2026-08-08T09:00:00Z",
                     "author": {"username": "@lonely"}},
                ],
            },
        ],
    }],
}


# --------------------------------------------------------------------------- fixtures & doubles


class _Log:
    """The `LogWriter` surface the adapter touches, and nothing else (module-local, house style).

    Positional-only, because the adapter passes `name=` as DATA on `virlo_payload`.
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.warnings: list[tuple[str, str, dict[str, Any]]] = []

    def event(self, event: str, message: str = "", /, **data: Any) -> None:
        self.events.append((event, message, data))

    def warn(self, event: str, message: str = "", /, **data: Any) -> None:
        self.warnings.append((event, message, data))

    def named(self, name: str) -> list[dict[str, Any]]:
        return [data for event, _message, data in self.events if event == name]


class _Session:
    """One MCP session: records every `(tool, args)` and answers from a canned payload map."""

    def __init__(self, payloads: dict[str, Any]) -> None:
        self._payloads = payloads
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool: str, args: dict[str, Any]) -> Any:
        self.calls.append((tool, dict(args)))
        return self._payloads.get(tool, {})


class _Pool:
    """`SessionPool`'s whole surface as far as `_monitor_item`/`_digest` are concerned."""

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


def _analysis() -> dict[str, Any]:
    return {"name": "AI Trends Tracker", "why_it_works": "proof over promise",
            "themes": [{"name": "agent demos", "confidence": 0.9,
                        "tactics": ["show the terminal"]}]}


def _corpus_topic(cfg: Config | None = None, log: _Log | None = None) -> TrendItem:
    """ONE topic assembled from the whole real sorted page — 100 videos + 100 slideshows.

    The analysis names a single theme, so the split yields exactly one topic and it owns every
    deduped row: the data channel this file is about is the same whether a monitor becomes one
    topic or nine, and one topic keeps the corpus arithmetic checkable by eye.
    """
    videos, shows = _corpus()
    return virlo._split_topics(MONITOR, _analysis(), videos, shows, cfg or Config(), log=log)[0]


# ---------------------------------------------------------------- A2: the sort reaches the wire


async def test_a2_the_adapter_asks_for_the_monitors_winners_on_both_media_tools() -> None:
    """The single biggest quality lever in the plan, asserted at the one place it can be lost.

    `get_top_videos` is only "top" anything if the caller says so; for this tool's whole history
    the arguments were `{monitor_id, limit: 50}` and Virlo answered in insertion order.
    """
    session = _Session({"get_monitor_analysis": _analysis(),
                        "get_top_videos": {"videos": []}, "get_top_slideshows": {"slideshows": []}})

    await virlo._monitor_item(_Pool(session), MONITOR, Config())

    media = {tool: args for tool, args in session.calls if tool != "get_monitor_analysis"}
    assert set(media) == {"get_top_videos", "get_top_slideshows"}
    for args in media.values():
        assert args == {"monitor_id": MONITOR, "limit": 100, "order_by": "views", "sort": "desc"}


async def test_a2_offset_appears_in_no_argument_the_adapter_ever_builds() -> None:
    """`offset` is a hard HTTP 400 at Virlo while its *responses* echo a derived one, so it is the
    one parameter name that looks legitimate. The wrapper refuses it structurally; the adapter must
    not try to route around that, on any call, including the two that take no media parameters."""
    session = _Session({"get_monitor_analysis": _analysis()})

    await virlo._monitor_item(_Pool(session), MONITOR, Config())

    assert session.calls  # the sweep actually ran
    assert all("offset" not in args for _tool, args in session.calls)


def test_a2_the_adapters_arguments_are_exactly_what_the_wrapper_accepts() -> None:
    """Caller and wrapper agree, checked against the wrapper's own local validator rather than by
    eye: a drifted constant (`order_by="view"`, `limit=101`) would raise here instead of failing
    live, one metered run later."""
    sent = virlo_server._media_params(
        virlo._MEDIA_LIMIT, None, virlo._MEDIA_ORDER_BY, virlo._MEDIA_SORT)

    assert sent == {"limit": 100, "order_by": "views", "sort": "desc"}
    assert virlo._MEDIA_LIMIT == virlo_server._MAX_LIMIT == 100  # one page, the deepest allowed


def test_a2_the_sorted_page_lands_view_ranked_on_the_topic_the_copy_call_quotes() -> None:
    """The sort's post-pivot consequence, on the real page: `TrendItem.posts` is view-ranked, so
    `P1` really is the monitor's strongest post — and `P1` is what `_fallback_copy` quotes and what
    FR-297b prints as the sort proof. Doubling the page (50 -> 100 rows) doubles the posts a topic
    can offer and changes none of the caps that bound a prompt."""
    topic = _corpus_topic()
    views = [post.views for post in topic.posts]

    assert len(topic.posts) > 100, "the whole sorted page reaches the topic"
    assert views == sorted(views, reverse=True)
    assert views[0] >= 1_000_000, "the corpus's top row is a real winner, not an insertion-order one"
    # Every few-shot list stays capped, so a doubled page cannot double a prompt.
    assert len(topic.hook_texts) <= virlo._MAX_EXEMPLARS
    assert len(topic.hashtags) <= virlo._MAX_HASHTAGS
    assert len(topic.panel_texts) == len(
        next((post.panel_texts for post in topic.posts if post.panel_texts), []))


# ------------------------------------------------------------- A13: Virlo's own labels, per row


def test_a13_the_three_labels_survive_wrapper_adapter_and_prompt() -> None:
    """End to end on the real page: `intelligence.hook_type` -> `_norm_video` -> `TrendItem` ->
    the one `{{trend_texts}}` row. The labels are the source's own vocabulary for what a post did,
    which is what a copywriter selecting among that post's strings is being asked to judge."""
    topic = _corpus_topic()

    assert topic.hook_types and topic.visual_hook_types and topic.emotional_tones
    rendered = build_context(trend=topic)["trend_texts"]
    row = next(line for line in rendered.splitlines() if line.startswith("Source's own labels:"))
    assert topic.hook_types[0] in row
    assert topic.visual_hook_types[0] in row and topic.emotional_tones[0] in row
    assert "hook" in row and "visual hook" in row and "emotional tone" in row
    assert row.count("\n") == 0  # ONE row, per §2.2 — the vocabulary, not an essay


def test_a13_labels_are_read_per_row_never_gated_on_the_agent_level_flag() -> None:
    """The contradiction that made an earlier draft defer this work, resolved by the corpus.

    The captured agent reports `data_intelligence_enabled: false` — yet 70 of its 100 video rows
    carry a populated `intelligence` block, because that flag gates NEW enrichment and rows
    enriched before it flipped keep theirs. Any read gated on the agent flag returns nothing here.
    """
    agent = _body("agent_detail.json")["data"]
    videos, _shows = _corpus()

    assert agent["data_intelligence_enabled"] is False
    assert sum(1 for row in videos if row["hook_type"]) >= 30
    assert _corpus_topic().hook_types  # ...and the adapter still reads them


def test_a13_a_row_that_classified_nothing_never_becomes_a_label() -> None:
    """Virlo writes a literal `"none"` on rows it could not classify (measured: 3 of 100 videos).

    Dropped BEFORE the cap, not after — otherwise three spellings of nothing would consume the
    slots real labels needed, and the prompt would carry `hook type: none`, which is worse than
    silence because it reads like a finding.
    """
    rows = [{"views": 9, "hook_type": "none"}, {"views": 8, "hook_type": None},
            {"views": 7, "hook_type": "  "}, {"views": 6, "hook_type": "Unknown"},
            {"views": 5, "hook_type": "story_tease"}]

    assert virlo._labels(rows, "hook_type") == ["story_tease"]
    assert virlo._labels(rows, "emotional_tone") == []  # absent field, absent row: same answer


def test_a13_labels_are_view_ranked_not_array_ranked() -> None:
    """`[*videos, *shows]` glues two independently sorted lists together, so array position says
    nothing about strength: a 400-view video would otherwise outrank a 4,000,000-view slideshow
    purely for being a video."""
    videos = [{"id": "v1", "views": 400, "hook_type": "weak_label", "hashtags": ["#weak"]}]
    shows = [{"id": "s1", "views": 4_000_000, "hook_type": "strong_label",
              "hashtags": ["#strong"]}]

    topic = virlo._split_topics(MONITOR, _analysis(), videos, shows, Config())[0]

    assert topic.hook_types == ["strong_label", "weak_label"]
    assert topic.hashtags == ["#strong", "#weak"]
    assert [post.post_id for post in topic.posts] == ["s1", "v1"]


# --------------------------------------------------------------------- A14: the real hashtags


def test_a14_real_hashtags_reach_the_copy_prompt_as_reference_material() -> None:
    """Rendered through the shipped `copywriter_system.md`, because "reaches the prompt" is the
    claim — a `TrendItem` field nothing renders is exactly the defect A14 exists to fix (the
    wrapper had extracted `hashtags` all along and nothing read them).

    Labelled as reference, not as output: post-pivot the tags a creative ships are the assigned
    post's own trailing run, peeled off its caption (§1.7.1), so these must not be pasted into a
    caption by the engine either.
    """
    topic = _corpus_topic()
    context = build_context(trend=topic, creative_format="image")

    prompt = PromptEngine().render("copywriter_system.md", context)

    assert topic.hashtags, "the real corpus carries hashtags on its winning posts"
    assert all(tag in prompt for tag in topic.hashtags)
    label = next(line for line in prompt.splitlines() if line.startswith("Hashtags on the winning"))
    assert "reference, not a list to copy" in label


def test_a14_hashtags_are_deduped_across_both_spellings_and_capped_per_post() -> None:
    """Two real edges in one call: Virlo ships `"#ai"` on one row and `"ai"` on the next, and a
    single motivational post can carry 39 tags. Without the per-post cap that one post fills the
    whole list, and the copywriter learns about that post rather than about the trend."""
    spammer = {"views": 10, "hashtags": [f"#tag{n}" for n in range(39)]}
    winner = {"views": 100, "hashtags": ["#AI", "ai", "  #ai  ", "claude", "#", ""]}

    tags = virlo._tags(virlo._ranked([spammer, winner]))

    assert tags[:2] == ["#AI", "#claude"]  # the winner leads, `ai`/`#ai` counted once
    assert sum(1 for tag in tags if tag.startswith("#tag")) == virlo._MAX_HASHTAGS_PER_POST
    assert len(tags) <= virlo._MAX_HASHTAGS
    assert all(tag.startswith("#") and len(tag) > 1 for tag in tags)


def test_a14_the_invented_slug_fallback_stays_the_last_resort_it_was() -> None:
    """Real tags are better INPUT, never a bypass of the copy call.

    `_fallback_copy` runs only when there was no model answer at all, and post-pivot it quotes the
    top post's caption — whose OWN trailing hashtags it peels off and ships (§1.7.1). The slug path
    is what is left when there is no post to take anything from, and it is unchanged: it still
    answers for a topic that carries real hashtags at topic level and no posts at all.
    """
    topic = TrendItem(history_key="t", monitor_id=MONITOR, name="AI Trends Tracker",
                      hashtags=["#claudecode", "#buildinpublic"])
    entry = PlanEntry(order=0, asset_id="a1", creative_format="image", platform="instagram",
                      language="en", aspect_ratio="1:1", trend_key="t")

    copyset = copywrite._fallback_copy(entry, topic)

    assert copyset.hashtags == ["#trends", "#tracker"]  # slugified from the NAME, as before
    assert not set(copyset.hashtags) & set(topic.hashtags)
    assert copywrite._hashtags("AI Trends Tracker") == copyset.hashtags


# ------------------------------------------------------- the digest: two values, no exemplars


async def test_the_digest_returns_cross_monitor_context_and_confidences_and_nothing_else() -> None:
    """`_digest` is a 2-TUPLE post-pivot (v2.0.0). The third element was A18's exemplar pool, and
    the tier it fed no longer exists: the visual authority is the local style registry (FR-290), so
    a global post's thumbnail has nothing to reference and its TEXT belongs to another niche.

    It remains THE ONLY METERED VIRLO CALL ($0.25), so the recorder answers from a literal.
    """
    groups = {"trends": [{"name": "AI agents", "ranking": 1, "confidence": 0.71,
                          "momentum_status": "rising", "views_per_hour": 900,
                          "top_exemplars": [{"post_id": "big", "views": 999,
                                             "thumbnail_url": "https://cdn.virlo.test/big.jpg"}]}]}
    session = _Session({"get_trends": {"groups": [groups]}})

    result = await virlo._digest(_Pool(session), None)

    assert len(result) == 2, "the exemplar payload is dropped"
    context, confidences = result
    assert "AI agents" in context and "rising" in context
    assert confidences == {"ai-agents": 0.71}
    assert "big" not in context, "no exemplar post reaches any caller"


async def test_the_wrapper_still_normalizes_the_exemplars_the_adapter_now_ignores() -> None:
    """The seam is unchanged on the wrapper side: `top_exemplars` is flattened into `_norm_video`'s
    vocabulary, so no second shape for "a post" enters the codebase. Nothing consumes it after the
    pivot — 20 §2's tool-table row goes with the media funnel at W3.5 — and it is asserted here so
    the removal is a decision rather than a discovery.
    """
    class _Response:
        is_success, status_code, text = True, 200, ""

        def json(self) -> Any:
            return DIGEST_BODY

    class _Client:
        async def get(self, path: str, params: Any = None) -> Any:
            assert path == "/trends/digest"
            return _Response()

    virlo_server._client = _Client()  # type: ignore[assignment]
    try:
        payload = await virlo_server.get_trends()
    finally:
        virlo_server._client = None

    exemplars = payload["groups"][0]["trends"][0]["top_exemplars"]
    assert [post["post_id"] for post in exemplars] == ["ex-weak", "ex-strong"]
    assert exemplars[1] == {"post_id": "ex-strong", "url": "https://tiktok.test/p/ex-strong",
                            "platform": "tiktok", "views": 4_000_000,
                            "thumbnail_url": "https://cdn.virlo.test/digest-strong.jpg",
                            "publish_date": "2026-08-09T09:00:00Z", "author": "@strong"}
