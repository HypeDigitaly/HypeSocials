"""A2 / A13 / A14 / A18 — the data channel from Virlo's wire to the prompt that spends money.

Four claims are pinned here, in the order they change what gets rendered:

1. **A2 — the sort reaches the wire.** The adapter asks for `order_by=views&sort=desc&limit=100`
   on both media tools and never sends `offset`. Unsorted, this tool drew every reference it has
   ever attached from the bottom of a 2,039-row pool: measured 2026-08-11, a median of 2,534 views
   against 1,940,676 sorted. A regression is invisible in output — the run still succeeds, on
   rubbish references — so it has to be visible here.
2. **A13 — Virlo's own labels survive** wrapper → adapter → prompt, view-ranked, absent-safe, and
   read PER ROW: the corpus monitor reports `data_intelligence_enabled: false` while 70 of its 100
   rows carry a populated `intelligence` block.
3. **A14 — the winning posts' real hashtags reach the copy prompt** as reference material, while
   the invented-from-slug fallback stays exactly what it was: the last resort, for its own case.
4. **A18 — the metered digest's exemplars are a LAST-RESORT tier.** Below every monitor-sourced
   set, rationed away by the download budget on a trend that has its own material, never a
   slideshow, and logged `reference_source=digest_exemplar` so a cross-niche image in a creative
   is traceable afterwards.

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

import pytest

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
#: `/trends/digest` bills — see `tests/fixtures/virlo/README.md`. Two exemplars on the first trend
#: (enough for `_MIN_THUMBS`), one on the second (deliberately not enough).
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

#: What `DIGEST_BODY`'s first trend becomes: two stills, view-ranked, one group.
EXEMPLAR_GROUP = ["https://cdn.virlo.test/digest-strong.jpg",
                  "https://cdn.virlo.test/digest-weak.jpg"]


# --------------------------------------------------------------------------- fixtures & doubles


@pytest.fixture(autouse=True)
def _isolated_reference_cache() -> Any:
    """`virlo` keeps its download cache in module globals; no test may inherit or leak one."""
    virlo._CACHE.clear()
    virlo._CACHE_DIR, virlo._CACHE_DIR_OWNED = None, False
    yield
    virlo._CACHE.clear()
    virlo._CACHE_DIR, virlo._CACHE_DIR_OWNED = None, False


class _Log:
    """The `LogWriter` surface the adapter touches, and nothing else (module-local, house style)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.warnings: list[tuple[str, str, dict[str, Any]]] = []

    def event(self, name: str, message: str, **data: Any) -> None:
        self.events.append((name, message, data))

    def warn(self, name: str, message: str, **data: Any) -> None:
        self.warnings.append((name, message, data))

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


def _corpus_item(cfg: Config | None = None, log: _Log | None = None) -> TrendItem:
    """One `TrendItem` assembled from the whole real sorted page — 100 videos + 100 slideshows."""
    videos, shows = _corpus()
    return virlo._build_item(MONITOR, _analysis(), videos, shows, cfg or Config(), log=log)


def _fake_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Substitute the per-image download unit so the real budget and pruning logic runs offline."""
    async def _download(client: Any, url: str, target: Path, attempts: int,
                        log: Any) -> Path | None:
        path = Path(target) / url.rsplit("/", 1)[-1]
        path.write_bytes(b"fixture-bytes")
        return path

    monkeypatch.setattr(virlo, "_download", _download)


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


def test_a2_doubling_the_page_doubles_the_candidates_but_not_the_downloads() -> None:
    """The one risk in raising `_MEDIA_LIMIT` 50 -> 100: per-row work now runs twice as often.

    Downloads are the only unbounded-looking consumer, and they are not: `_download_references`
    spends `media_download_cap` down the group list in order, so 200 rows and ~90 qualifying sets
    still queue at most the cap. Asserted on the real page, which is what a live run gets.
    """
    cfg = Config()
    item = _corpus_item(cfg)
    per_job = cfg.sources.reference_images_per_job

    assert len(item.reference_groups) > 20  # the whole sorted page reaches the candidate pool
    assert all(0 < len(group) <= per_job for group in item.reference_groups)
    queued, budget = [], cfg.sources.media_download_cap
    for group in item.reference_groups:  # `_download_references`' own arithmetic, spelled out
        queued += group[:max(0, budget)]
        budget -= len(group)
    assert len(queued) <= cfg.sources.media_download_cap
    # Every few-shot list stays capped too, so a doubled page cannot double a prompt.
    assert len(item.hook_texts) <= virlo._MAX_EXEMPLARS
    assert len(item.hashtags) <= virlo._MAX_HASHTAGS


# ------------------------------------------------------------- A13: Virlo's own labels, per row


def test_a13_the_three_labels_survive_wrapper_adapter_and_prompt() -> None:
    """End to end on the real page: `intelligence.hook_type` -> `_norm_video` -> `TrendItem` ->
    the one `{{trend_texts}}` row. FR-100 asks the copywriter to DERIVE a hook pattern that the
    source already classified, so this row is the difference between a guess and a label."""
    item = _corpus_item()

    assert item.hook_types and item.visual_hook_types and item.emotional_tones
    rendered = build_context(trend=item)["trend_texts"]
    row = next(line for line in rendered.splitlines() if line.startswith("Source's own labels:"))
    assert item.hook_types[0] in row
    assert item.visual_hook_types[0] in row and item.emotional_tones[0] in row
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
    assert _corpus_item().hook_types  # ...and the adapter still reads them


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
    videos = [{"views": 400, "hook_type": "weak_label", "hashtags": ["#weak"]}]
    shows = [{"views": 4_000_000, "hook_type": "strong_label", "hashtags": ["#strong"]}]

    item = virlo._build_item(MONITOR, _analysis(), videos, shows, Config())

    assert item.hook_types == ["strong_label", "weak_label"]
    assert item.hashtags == ["#strong", "#weak"]


# --------------------------------------------------------------------- A14: the real hashtags


def test_a14_real_hashtags_reach_the_copy_prompt_as_reference_material() -> None:
    """Rendered through the shipped `copywriter_system.md`, because "reaches the prompt" is the
    claim — a `TrendItem` field nothing renders is exactly the defect A14 exists to fix (the
    wrapper had extracted `hashtags` all along and nothing read them).

    Labelled as reference, not as output: the model still chooses, and the tags must not be pasted
    into a caption by the engine.
    """
    item = _corpus_item()
    context = build_context(trend=item, creative_format="image")

    prompt = PromptEngine().render("copywriter_system.md", context)

    assert item.hashtags, "the real corpus carries hashtags on its winning posts"
    assert all(tag in prompt for tag in item.hashtags)
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
    """Real tags are better INPUT, never a bypass of the copywriter.

    `_fallback_copy` runs only when there was no model answer at all; making it emit the source's
    tags verbatim would turn reference material into a mandate and hand the model's one editorial
    job to a list slice. So the slug path is unchanged, and it still answers for a trend that has
    real hashtags sitting right there.
    """
    trend = TrendItem(history_key="t", monitor_id=MONITOR, name="AI Trends Tracker",
                      hashtags=["#claudecode", "#buildinpublic"])
    entry = PlanEntry(order=0, asset_id="a1", creative_format="image", platform="instagram",
                      language="en", aspect_ratio="1:1", trend_key="t")

    copyset = copywrite._fallback_copy(entry, trend)

    assert copyset.hashtags == ["#trends", "#tracker"]  # slugified from the NAME, as before
    assert not set(copyset.hashtags) & set(trend.hashtags)
    assert copywrite._hashtags("AI Trends Tracker") == copyset.hashtags


# ------------------------------------------------------------ A18: the digest's last-resort tier


async def test_a18_the_digest_stops_discarding_its_exemplars() -> None:
    """`/trends/digest` is the only metered Virlo call and this normalizer used to throw its
    exemplars away. Flattened into `_norm_video`'s vocabulary — one still per post, a permalink, a
    view count and a handle — so no second shape for "a post" enters the codebase.

    The digest is NOT called here: the recorder answers from a literal (README: it bills).
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


async def test_a18_the_adapter_pools_the_exemplars_view_ranked_per_digest_trend() -> None:
    """`_digest`'s third return. One list per digest trend — a set stays ONE subject (FR-91) even
    though it is not one creator — and thumbnail-less posts are dropped, since a reference tier
    made of posts with no image is not a tier."""
    groups = {"trends": [{"name": "AI agents", "top_exemplars": [
        {"post_id": "small", "views": 1, "thumbnail_url": "https://cdn.virlo.test/small.jpg"},
        {"post_id": "big", "views": 999, "thumbnail_url": "https://cdn.virlo.test/big.jpg"},
        {"post_id": "imageless", "views": 500, "thumbnail_url": ""},
    ]}]}
    session = _Session({"get_trends": {"groups": [groups]}})

    _context, _confidences, exemplars = await virlo._digest(_Pool(session), None)

    assert [post["post_id"] for post in exemplars[0]] == ["big", "small"]
    assert len(exemplars) == 1


def test_a18_exemplars_are_offered_strictly_below_every_monitor_sourced_set() -> None:
    """Position IS the safety property: this material is global, not this niche's, so it must never
    outrank a monitor's own posts. Appended after `_pick_set` already chose, so it can neither
    become the chosen set of a trend that had one nor displace a group in rotation order —
    `reference_groups[k % len]` reaches it last, if ever."""
    item = _thin_item()
    monitor_groups = [list(group) for group in item.reference_groups]

    offered = virlo._offer_digest_exemplars([item], _pool(), Config())

    assert monitor_groups and item.reference_groups[:len(monitor_groups)] == monitor_groups
    assert item.reference_groups[len(monitor_groups):] == [EXEMPLAR_GROUP]
    assert offered == frozenset(EXEMPLAR_GROUP)
    assert item.is_slideshow is True  # the CHOSEN set is still the monitor's own slideshow


def test_a18_a_lone_exemplar_never_becomes_a_set_and_never_a_slideshow() -> None:
    """An exemplar thumbnail is ONE still per post, exactly like a video's — so a set of them is a
    `_MIN_THUMBS` frame family, and one of them is nothing at all. A single still masquerading as a
    panel set would hand FR-90 a carousel affinity nobody earned and the deck would be invented."""
    item = TrendItem(history_key="t", monitor_id=MONITOR, name="bare")
    lonely = _pool()[1]  # the digest's second trend ships exactly one exemplar

    virlo._offer_digest_exemplars([item], [lonely], Config())

    assert item.reference_groups == []
    assert virlo._MIN_THUMBS == 2 and len(lonely) == 1
    assert item.is_slideshow is False


async def test_a18_a_rich_trend_is_offered_nothing_while_a_bare_one_is_rescued_and_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tier's whole behaviour in one pass, because the two halves only mean something together.

    A trend whose own sets already fill `media_download_cap` is offered nothing — it has material
    to rotate through and cross-niche pictures would cost fidelity for no gain. A trend with NO
    material keeps the exemplar group, ships images instead of `text_only`, and is logged
    `reference_source=digest_exemplar` so a cross-niche image in a creative stays traceable without
    re-running anything.

    ⚠️ The eligibility test must be explicit, and this is the fixture that proves it: `_CACHE` is
    shared across items, so the bare trend's download leaves both exemplar urls cached and a rich
    trend holding the same group would sail through `_download_references`' liveness prune. The
    download budget cannot be the gate here.
    """
    log = _Log()
    _fake_downloads(monkeypatch)
    rich, bare = _corpus_item(), TrendItem(history_key="bare", monitor_id=MONITOR, name="bare")

    offered = virlo._offer_digest_exemplars([rich, bare], _pool(), Config())
    await virlo._download_references([rich, bare], Config(), tmp_path, log)
    virlo._log_digest_exemplars([rich, bare], offered, log)

    assert all(url not in offered for group in rich.reference_groups for url in group)
    assert bare.reference_groups == [EXEMPLAR_GROUP]
    assert all(url in virlo._CACHE for url in EXEMPLAR_GROUP)  # cached, still not the rich one's
    assert bare.text_only is False and bare.is_slideshow is False
    attached = log.named("digest_exemplar_attached")
    assert len(attached) == 1
    assert attached[0]["reference_source"] == "digest_exemplar"
    assert attached[0]["trend"] == "bare" and attached[0]["groups"] == [0]


def _thin_item() -> TrendItem:
    """A trend whose monitor gave it ONE small set — under the download cap, so the digest tier is
    open to it, and with a monitor-sourced group present so "appended below" is checkable."""
    shows = [{"id": "own-1", "url": "https://virlo.test/p/own", "views": 900,
              "author_username": "@own", "panel_texts": ["OWN HOOK"],
              "image_urls": [f"https://cdn.virlo.test/own-{n}.jpg" for n in (1, 2, 3)]}]
    return virlo._build_item(MONITOR, _analysis(), [], shows, Config())


def _pool() -> list[list[dict[str, Any]]]:
    """The exemplar pool `_digest` would return for `DIGEST_BODY`, built through the real wrapper
    normalizer so the test data cannot drift from the shape the wrapper actually emits."""
    trends = DIGEST_BODY["data"][0]["trends"]
    return [virlo._ranked([virlo_server._norm_exemplar(post) for post in row["top_exemplars"]])
            for row in trends]
