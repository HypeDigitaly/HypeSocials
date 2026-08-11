"""FR-7 / FR-24 — the reference-set mechanism: EVERY candidate built, the freshest one CHOSEN, and
every field the creative is shaped by read off THAT set.

This file exists because of a design that was rejected on review. That design merely **reordered**
`reference_groups` so a fresh set landed at index 0 — while `panel_texts`, `narrative_arc`,
`text_density`, `is_slideshow` and `virlo_url` were all still computed from the *original* group 0.
It changed the order and not the input: headline, caption, hook pattern and rendered style would
have repeated while three CDN urls differed, and the run would have reported success. Two facts make
that regression detectable only with a fixture built for it:

- the fixture's **strongest** candidate is deliberately a *used* slideshow whose panel metadata,
  arc, density and permalink differ visibly from the **chosen** one's, so a reorder-only
  implementation prints `STALE …` where this suite demands `FRESH …`;
- the fixture qualifies **7** candidate sets where the pre-fix code built exactly
  `media_download_cap ÷ reference_images_per_job` = 2, so a candidate cap that gates *choice*
  rather than downloads fails here too.

The second half pins §2.3's three motion tiers, and above all tier 3: freshness must NEVER cost a
reel. `_pick_motion` returns `None` only when no video carries a url at all — never because
everything has been used. One reel measured $4.78; a repeated motion source is a cosmetic loss, a
missing one is a paid loss.

Everything here is offline and synchronous apart from the one download test, which substitutes
`virlo._download` (the per-image unit) so the real pruning logic runs with **no network, no MCP
subprocess and no API key**. `sources/virlo.py` is imported directly rather than through the
`hypesocials.sources` facade because the facade's only entry point opens a `SessionPool`; the
mechanism under test is pure normalization behind it. Every file written lands in `tmp_path`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from hypesocials.config import Config
from hypesocials.models import ReferenceSet
from hypesocials.sources import virlo

#: The monitor every fixture row belongs to. It also spells the `_post_id` positional fallback:
#: `monitor-1:4` is the fifth slideshow, the one row deliberately shipped with no id and no url.
MONITOR = "monitor-1"

# Post ids, named so an assertion reads as the story it tells.
STALE = "post-stale-hero"  # strongest candidate of all, and already used — the reorder-only trap
ALSO_USED = "post-also-used"  # second strongest, also used: the choice must skip MORE than one
FRESH = "post-fresh-winner"  # what FR-7 must choose
RUNNER_UP = "post-runner-up"  # the next fresh set — group 1, and the top-up download
NO_ID = f"{MONITOR}:4"  # a row with neither `id` nor `url`: positional, never `id(row)`
FRESH_VID_A = "vid-fresh-a"  # @fresh_creator's best clip — tier 1, at 12k views
FRESH_VID_B = "vid-fresh-b"
STRANGER_A = "vid-stranger-a"  # 5,000,000 views and the wrong creator — tier 2 only
STRANGER_B = "vid-stranger-b"
STRANGER_C = "vid-stranger-c"

#: Every slideshow post id, freshest-first order irrelevant — used to starve the image choice.
ALL_SETS = (STALE, ALSO_USED, FRESH, RUNNER_UP, NO_ID)
ALL_VIDEOS = (FRESH_VID_A, FRESH_VID_B, STRANGER_A, STRANGER_B, STRANGER_C)


# --------------------------------------------------------------------------- fixtures & builders


@pytest.fixture(autouse=True)
def _isolated_reference_cache() -> Any:
    """`virlo` keeps its download cache in module globals; no test may inherit or leak one.

    Cleared rather than `cleanup()`-ed: every path this file puts in there lives under `tmp_path`,
    which pytest removes, and `cleanup()` would `rmdir` a folder the next test still wants.
    """
    virlo._CACHE.clear()
    virlo._CACHE_DIR, virlo._CACHE_DIR_OWNED = None, False
    yield
    virlo._CACHE.clear()
    virlo._CACHE_DIR, virlo._CACHE_DIR_OWNED = None, False


class _Log:
    """The `LogWriter` surface the adapter touches, and nothing else (module-local per house style).

    Real `LogWriter` opens run files; the two methods below are the whole seam `_build_item` and
    `_download_references` use, so a recorder is both sufficient and honest.
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.warnings: list[tuple[str, str, dict[str, Any]]] = []

    def event(self, name: str, message: str, **data: Any) -> None:
        self.events.append((name, message, data))

    def warn(self, name: str, message: str, **data: Any) -> None:
        self.warnings.append((name, message, data))

    def choice(self) -> tuple[str, dict[str, Any]]:
        """The single `reference_choice` event FR-7/FR-24 require per trend."""
        rows = [(message, data) for name, message, data in self.events
                if name == "reference_choice"]
        assert len(rows) == 1, self.events
        return rows[0]

    def warned(self, name: str) -> list[str]:
        return [message for event, message, _ in self.warnings if event == name]


def _config(**sources_kwargs: Any) -> Config:
    """A default `Config`; only `sources.*` matters here (`tests/test_plan.py:19`'s pattern)."""
    cfg = Config()
    for key, value in sources_kwargs.items():
        setattr(cfg.sources, key, value)
    return cfg


def _slideshow(slug: str, *, post_id: str | None, views: int, panels: int, author: str,
               texts: Sequence[str] = (), arc: str = "", density: str = "",
               permalink: str | None = None) -> dict[str, Any]:
    """One `get_top_slideshows` row in `virlo_mcp/server.py:_norm_slideshow`'s exact shape."""
    return {
        "id": post_id,
        "url": permalink,
        "platform": "tiktok",
        "description": f"{slug} slideshow",
        "thumbnail_url": f"https://cdn.virlo.test/{slug}-cover.jpg",
        "publish_date": "2026-08-08T09:00:00Z",
        "views": views,
        "likes": views // 20,
        "shares": views // 100,
        "comments": views // 200,
        "bookmarks": views // 300,
        "author_username": author,
        "hashtags": [],
        "image_urls": [f"https://cdn.virlo.test/{slug}-{n}.jpg" for n in range(1, panels + 1)],
        "panel_count": panels,
        "panel_texts": list(texts),
        "hook_text": f"{slug} hook",
        "narrative_arc": arc,
        "text_density": density,
        "summary": f"{slug} summary",
        "intelligence_status": "ready",
    }


def _video(slug: str, *, post_id: str, views: int, author: str,
           complexity: str = "low") -> dict[str, Any]:
    """One `get_top_videos` row in `_norm_video`'s shape.

    `visual_complexity` is the lever the creator families are ranked by (`_frame_quality`): `low`
    scores 1.0 and `high` scores 0.0, so which family leads is fixed by the fixture rather than by
    view counts — the stranger's 5,000,000 views must not be what decides.
    """
    handle = author.lstrip("@")
    return {
        "id": post_id,
        "url": f"https://www.tiktok.com/@{handle}/video/{slug}",
        "platform": "tiktok",
        "description": f"{slug} clip",
        "thumbnail_url": f"https://cdn.virlo.test/{slug}-thumb.jpg",
        "publish_date": "2026-08-08T09:00:00Z",
        "views": views,
        "likes": views // 20,
        "shares": views // 100,
        "comments": views // 200,
        "bookmarks": views // 300,
        "author_username": author,
        "hashtags": [],
        "hook_text": f"{slug} hook",
        "text_overlay_content": f"{slug} overlay",
        "summary": f"{slug} summary",
        "has_face_visible": False,
        "has_text_overlay": False,
        "visual_complexity": complexity,
        "intelligence_status": "ready",
    }


def _payload() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """`(videos, slideshows)` for one monitor — freshly built on every call.

    Freshly built on purpose: two calls produce EQUAL data in DIFFERENT memory, which is what makes
    the `id(row)` assertions below meaningful.

    Qualifying candidates, strongest first (`_reference_groups` ranks slideshows above creator
    families, then by frame quality, then by views):

        1. `STALE`      900k views, USED  — panel texts `STALE …`, arc `stale-…`, density heavy
        2. `ALSO_USED`  850k views, USED
        3. `FRESH`      800k views, fresh — panel texts `FRESH …`, arc `fresh-…`, density light
        4. `RUNNER_UP`  700k views, fresh
        5. `NO_ID`      600k views, fresh — positional id `monitor-1:4`
        6. @fresh_creator's two clips (frame quality 1.0)
        7. @stranger's three clips (frame quality 0.0, despite 5,000,000 views)

    Plus one two-panel slideshow with the HIGHEST views of all, which must not qualify at all
    (`_MIN_PANELS` is 3) — so "count the qualifying sets" cannot be passed by counting rows.
    """
    shows = [
        _slideshow("stale-hero", post_id=STALE, views=900_000, panels=3, author="@stale_creator",
                   texts=["STALE HOOK", "STALE MIDDLE", "STALE CLOSE"],
                   arc="stale-arc-hook-payoff", density="heavy",
                   permalink="https://virlo.test/p/stale-hero"),
        _slideshow("also-used", post_id=ALSO_USED, views=850_000, panels=3, author="@also_used",
                   texts=["ALSO USED HOOK"], arc="also-used-arc", density="medium",
                   permalink="https://virlo.test/p/also-used"),
        _slideshow("fresh-winner", post_id=FRESH, views=800_000, panels=4, author="@fresh_creator",
                   texts=["FRESH HOOK", "FRESH MIDDLE", "FRESH TURN", "FRESH CLOSE"],
                   arc="fresh-arc-hook-escalation-payoff", density="light",
                   permalink="https://virlo.test/p/fresh-winner"),
        _slideshow("runner-up", post_id=RUNNER_UP, views=700_000, panels=3, author="@runner_up",
                   texts=["RUNNER UP HOOK"], arc="runner-up-arc", density="medium",
                   permalink="https://virlo.test/p/runner-up"),
        _slideshow("no-id", post_id=None, views=600_000, panels=3, author="@no_id_creator",
                   texts=["NO ID HOOK"], arc="no-id-arc", density="medium", permalink=None),
        _slideshow("single-panel", post_id="post-single-panel", views=990_000, panels=2,
                   author="@single_panel", texts=["SINGLE"], arc="single-arc", density="heavy",
                   permalink="https://virlo.test/p/single-panel"),
    ]
    videos = [
        _video("fresh-a", post_id=FRESH_VID_A, views=12_000, author="@fresh_creator"),
        _video("fresh-b", post_id=FRESH_VID_B, views=11_000, author="@fresh_creator"),
        _video("stranger-a", post_id=STRANGER_A, views=5_000_000, author="@stranger",
               complexity="high"),
        _video("stranger-b", post_id=STRANGER_B, views=4_000_000, author="@stranger",
               complexity="high"),
        _video("stranger-c", post_id=STRANGER_C, views=3_000_000, author="@stranger",
               complexity="high"),
    ]
    return videos, shows


#: What the fixture qualifies, spelled as its own arithmetic so the number is checkable by eye:
#: five slideshows with >= `_MIN_PANELS` panels, plus two creator families with >= `_MIN_THUMBS`
#: thumbnails. The two-panel slideshow qualifies as neither.
QUALIFYING_SETS = 5 + 2


def _analysis() -> dict[str, Any]:
    return {
        "name": "AI Trends Tracker",
        "why_it_works": "pattern interrupt in the first frame",
        "themes": [{"name": "agent demos", "tactics": ["show the terminal"],
                    "why_it_works": "proof over promise", "confidence": 0.8}],
        "timing_pattern": "weekday mornings",
    }


def _item(*, used: Sequence[str] = (), log: _Log | None = None, cfg: Config | None = None,
          payload: tuple[list[dict[str, Any]], list[dict[str, Any]]] | None = None) -> Any:
    """One assembled `TrendItem` — the unit under test, no I/O of any kind."""
    videos, shows = payload if payload is not None else _payload()
    return virlo._build_item(MONITOR, _analysis(), videos, shows, cfg or _config(),
                             used=frozenset(used), log=log)


# ------------------------------------------------------- every candidate is built, not exactly two


def test_fr7_every_qualifying_candidate_is_built_not_the_download_cap_divided_by_the_job_size() -> None:
    """`media_download_cap` bounds DOWNLOADS, never the candidate pool.

    Gating candidates on it left exactly `6 ÷ 3 = 2` sets per monitor where a live monitor qualifies
    ~36 (`spikes/RESULTS.md:163`) — and with two candidates a week of runs cannot help repeating.
    The number asserted is what the fixture qualifies, computed independently of the cap.
    """
    cfg = _config()
    rationed = cfg.sources.media_download_cap // cfg.sources.reference_images_per_job

    sets = virlo._reference_groups(*_payload(), cfg, MONITOR)

    assert len(sets) == QUALIFYING_SETS == 7
    assert len(sets) != rationed  # the pre-fix arithmetic: 6 ÷ 3 = 2
    assert rationed == 2, "fixture assumes the shipped 6/3 defaults"
    # The item carries every one of them as a reference group, strongest/freshest first.
    assert len(_item().reference_groups) == QUALIFYING_SETS


def test_fr91_a_two_panel_slideshow_never_becomes_a_candidate_however_strong_it_is() -> None:
    """`_MIN_PANELS` is 3 (RESULTS.md §A: 14/50 live slideshows are single-image). The fixture's
    two-panel row has the highest views in the payload, so a count that ignored the panel screen
    would show up as 8 sets and a chosen set of two urls."""
    urls = [url for candidate in virlo._reference_groups(*_payload(), _config(), MONITOR)
            for url in candidate.urls]

    assert not any("single-panel" in url for url in urls)


# --------------------------------------------------------------------- the freshest unused is CHOSEN


def test_fr7_the_freshest_unused_candidate_is_chosen_over_two_stronger_used_ones() -> None:
    """"the strongest candidate none of whose posts appear in the history window".

    Two used sets sit above the chosen one, so an implementation that skipped only the first would
    land on `ALSO_USED` and this fails.
    """
    item = _item(used=[STALE, ALSO_USED])

    assert item.chosen_post_ids == (FRESH,)
    assert item.reference_groups[0] == [f"https://cdn.virlo.test/fresh-winner-{n}.jpg"
                                        for n in (1, 2, 3)]


def test_fr7_every_panel_shaped_field_is_derived_from_the_CHOSEN_set_not_the_strongest() -> None:
    """THE test the rejected reorder-only design fails.

    That design put a fresh set at index 0 and left every derived field reading the original group 0
    — so on this fixture it would have produced `STALE …` panel texts, `stale-arc-hook-payoff`,
    density `heavy` and the `stale-hero` permalink while advertising fresh reference urls. Each
    assertion below names the value that design would have printed.
    """
    item = _item(used=[STALE, ALSO_USED])

    assert item.panel_texts == ["FRESH HOOK", "FRESH MIDDLE", "FRESH TURN", "FRESH CLOSE"]
    assert item.narrative_arc == "fresh-arc-hook-escalation-payoff"
    assert item.text_density == "light"
    assert item.virlo_url == "https://virlo.test/p/fresh-winner"
    assert item.is_slideshow is True
    assert item.chosen_post_ids == (FRESH,)
    # None of the stale set's own values may survive anywhere in the derived fields.
    assert not any(text.startswith("STALE") for text in item.panel_texts)
    assert "stale" not in item.narrative_arc
    assert item.text_density != "heavy"
    assert item.virlo_url is not None and "stale-hero" not in item.virlo_url


def test_fr90_is_slideshow_follows_the_chosen_set_even_when_the_strongest_is_a_slideshow() -> None:
    """`is_slideshow` drives FR-90's carousel affinity, so it is the one derived field a
    reorder-only design gets wrong in the *format* rather than in the words.

    With every slideshow used the choice falls to a creator family: no panels, no arc, no density,
    and the permalink is that creator's clip. The strongest candidate is still the `STALE`
    slideshow, so the rejected design would have claimed `is_slideshow=True` with `STALE …` panel
    texts while attaching video thumbnails.
    """
    item = _item(used=ALL_SETS)

    assert item.is_slideshow is False
    assert item.panel_texts == []
    assert item.narrative_arc == "" and item.text_density == ""
    assert item.chosen_post_ids == (FRESH_VID_A, FRESH_VID_B)
    assert item.virlo_url == "https://www.tiktok.com/@fresh_creator/video/fresh-a"
    assert item.reference_groups[0] == ["https://cdn.virlo.test/fresh-a-thumb.jpg",
                                        "https://cdn.virlo.test/fresh-b-thumb.jpg"]


def test_fr7_when_every_candidate_is_used_a_set_still_ships_but_is_reported_stale() -> None:
    """"an image-less trend is worse than a repeated one" — the strongest is chosen and reported
    stale, so `chosen_post_ids` stays empty and `plan.select`'s monitor-level window decides the
    exclusion instead of the adapter silently claiming freshness."""
    log = _Log()
    item = _item(used=[*ALL_SETS, *ALL_VIDEOS], log=log)

    assert item.chosen_post_ids == ()  # nothing fresh was attached, so nothing may be burned
    assert item.reference_groups[0][0].startswith("https://cdn.virlo.test/stale-hero-")
    assert item.text_only is False  # it still ships images
    message, data = log.choice()
    assert data["set_fresh"] is False and "repeat" in message


def test_fr7_the_choice_and_its_candidate_count_are_logged_once_per_trend() -> None:
    """FR-7 requires exclusions and repeats to stay individually explainable; the adapter's single
    `reference_choice` event is where a "why did today look like yesterday" question is answered."""
    log = _Log()
    item = _item(used=[STALE, ALSO_USED], log=log)

    message, data = log.choice()
    assert data["candidate_sets"] == QUALIFYING_SETS
    assert data["set_fresh"] is True
    assert data["post_ids"] == [FRESH]
    assert data["trend"] == item.history_key == MONITOR
    assert "fresh" in message


# ---------------------------------------------------------------- ids, atomicity and determinism


def test_fr7_post_ids_are_stable_across_runs_and_are_never_the_row_memory_address() -> None:
    """`_dedupe` falls back to `id(row)`; if that ever leaked into a post id, every id would differ
    on every run, `posts` in `trend_history.json` would grow forever and freshness would silently
    stop working while reporting success.

    The row exercised here carries neither `id` nor `url`, so it takes the positional fallback —
    which must be `monitor:index`, identical for two independently built payloads.
    """
    first_payload, second_payload = _payload(), _payload()
    starved = [STALE, ALSO_USED, FRESH, RUNNER_UP]  # leaves the id-less row as the only fresh set
    addresses = {str(id(row)) for group in first_payload for row in group}

    first = _item(used=starved, payload=first_payload)
    second = _item(used=starved, payload=second_payload)

    assert first.chosen_post_ids == (NO_ID,) == (f"{MONITOR}:4",)
    assert second.chosen_post_ids == first.chosen_post_ids
    assert not addresses & set(first.chosen_post_ids)
    assert not any(part.isdigit() and len(part) > 8
                   for post in first.chosen_post_ids for part in post.split(":"))


def test_fr7_selection_is_deterministic_on_identical_input() -> None:
    """Same payload twice (in different memory), same everything — a run must be reproducible from
    the same Virlo answer, or "the freshest unused set" is not a rule but a coin toss."""
    used = [STALE, ALSO_USED]
    first, second = _item(used=used, payload=_payload()), _item(used=used, payload=_payload())

    for field in ("chosen_post_ids", "reference_groups", "panel_texts", "narrative_arc",
                  "text_density", "is_slideshow", "virlo_url", "winning_video_url",
                  "winning_video_post_id"):
        assert getattr(first, field) == getattr(second, field), field


def test_a_reference_set_is_atomic_so_its_ids_and_its_urls_cannot_be_aligned_by_hand() -> None:
    """The invariant that replaced the desynchronising parallel lists: a candidate's urls, its post
    ids and the panel metadata derived from choosing it are ONE value object."""
    sets = virlo._reference_groups(*_payload(), _config(), MONITOR)

    assert all(isinstance(candidate, ReferenceSet) for candidate in sets)
    assert all(candidate.urls and candidate.post_ids for candidate in sets)
    chosen, ordered, fresh = virlo._pick_set(sets, frozenset([STALE, ALSO_USED]))
    assert chosen is ordered[0] and fresh is True
    assert chosen.post_ids == (FRESH,) and chosen.panel_texts[0] == "FRESH HOOK"
    # Reordered, never dropped and never copied — compared by identity, since a `ReferenceSet` is a
    # mutable dataclass and therefore unhashable.
    assert sorted(map(id, ordered)) == sorted(map(id, sets))


def test_pick_set_returns_an_empty_reference_set_rather_than_none_when_nothing_qualifies() -> None:
    """Callers branch on nothing: `_build_item` reads `chosen.panel_texts` unconditionally, so a
    monitor that offered no candidate at all must still yield a `ReferenceSet`."""
    chosen, ordered, fresh = virlo._pick_set([], frozenset())

    assert isinstance(chosen, ReferenceSet)
    assert (chosen.urls, chosen.post_ids, ordered, fresh) == ([], (), [], False)


# ---------------------------------------------------------- a dead CDN url cannot desynchronise ids


async def test_fr247_a_partly_dead_chosen_set_keeps_its_surviving_urls_and_its_post_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One dead image drops that image only (FR-32/33/247) — the set was still attached, so its post
    ids are still what history must burn."""
    log = _Log()
    item = _item(used=[STALE, ALSO_USED], log=log)
    dead = {"https://cdn.virlo.test/fresh-winner-2.jpg"}
    _fake_downloads(monkeypatch, dead)

    await virlo._download_references([item], _config(), tmp_path, log)

    assert item.chosen_post_ids == (FRESH,)
    assert item.reference_groups[0] == ["https://cdn.virlo.test/fresh-winner-1.jpg",
                                        "https://cdn.virlo.test/fresh-winner-3.jpg"]
    assert log.warned("reference_shortfall")  # judged on the CHOSEN set, per FR-247
    assert virlo._CACHE_DIR == tmp_path  # nothing was written outside tmp_path


async def test_fr7_a_fully_dead_chosen_set_burns_no_post_id_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The atomicity that matters most: post ids are recorded for what was ATTACHED.

    When every url of the chosen set dies, the trend still ships on the next candidate's images —
    but claiming the dead set's ids would tell `trend_history.json` a post was used that never
    reached a render job, and claiming the surviving group's ids would burn a set that was never
    chosen. Both are lies; the answer is neither.
    """
    log = _Log()
    item = _item(used=[STALE, ALSO_USED], log=log)
    dead = {f"https://cdn.virlo.test/fresh-winner-{n}.jpg" for n in (1, 2, 3)}
    _fake_downloads(monkeypatch, dead)

    await virlo._download_references([item], _config(), tmp_path, log)

    assert item.chosen_post_ids == ()
    assert RUNNER_UP not in item.chosen_post_ids and FRESH not in item.chosen_post_ids
    assert item.reference_groups[0] == [f"https://cdn.virlo.test/runner-up-{n}.jpg"
                                        for n in (1, 2, 3)]
    assert item.text_only is False


def _fake_downloads(monkeypatch: pytest.MonkeyPatch, dead: set[str]) -> None:
    """Substitute the per-image download unit: `None` is exactly how a dead url reports itself.

    Patching `_download` rather than `httpx` keeps the real queueing, cap arithmetic and pruning in
    `_download_references` under test while guaranteeing no socket is opened. `AsyncClient` is still
    constructed and entered by the code — neither does any I/O.
    """
    async def _download(client: Any, url: str, target: Path, attempts: int,
                        log: Any) -> Path | None:
        if url in dead:
            return None
        path = Path(target) / url.rsplit("/", 1)[-1]
        path.write_bytes(b"fixture-bytes")
        return path

    monkeypatch.setattr(virlo, "_download", _download)


# --------------------------------------------------------------------- FR-24's three motion tiers


def test_fr24_tier1_a_fresh_same_creator_video_beats_a_higher_viewed_stranger() -> None:
    """Tier 1 is freshness AND coherence: a slideshow's copy must not be animated by a stranger's
    clip. `@fresh_creator`'s 12,000-view clip wins over `@stranger`'s 5,000,000-view one because
    the chosen set is `@fresh_creator`'s slideshow."""
    log = _Log()
    item = _item(used=[STALE, ALSO_USED], log=log)

    assert item.winning_video_post_id == FRESH_VID_A
    assert item.winning_video_url == "https://www.tiktok.com/@fresh_creator/video/fresh-a"
    assert log.choice()[1]["motion_tier"] == "fresh_same_creator"


def test_fr24_tier2_with_no_creator_match_the_highest_viewed_fresh_video_wins() -> None:
    """Both of `@fresh_creator`'s clips are used, so coherence is unavailable and views decide
    among what is left — `@stranger`'s 5,000,000-view clip."""
    log = _Log()
    item = _item(used=[STALE, ALSO_USED, FRESH_VID_A, FRESH_VID_B], log=log)

    assert item.winning_video_post_id == STRANGER_A
    assert log.choice()[1]["motion_tier"] == "fresh"
    assert item.chosen_post_ids == (FRESH,)  # the image choice is unaffected by motion freshness


def test_fr24_tier3_every_video_used_still_returns_the_top_video_and_logs_repeat() -> None:
    """THE non-negotiable one. Motion-reference freshness is best-effort and must NEVER block a
    reel: a repeated motion source is a cosmetic loss, a failed reel is a paid one ($4.78 measured,
    and the reel already degrades gracefully to `in_model` when no reference exists).

    Only the motion pool is exhausted here, so the image set is still fresh — which isolates the
    claim to motion alone.
    """
    log = _Log()
    item = _item(used=[STALE, ALSO_USED, *ALL_VIDEOS], log=log)

    assert item.winning_video_post_id == STRANGER_A  # the top video, repeated deliberately
    assert item.winning_video_url is not None
    assert log.choice()[1]["motion_tier"] == "repeat"
    assert item.chosen_post_ids == (FRESH,)


def test_fr24_pick_motion_returns_none_only_when_no_video_carries_a_url() -> None:
    """The one legitimate `None`, pinned so the freshness `None` cannot be reintroduced as "the
    same thing". Every video used, tier 3 fires; no video at all, and only then is there nothing to
    return."""
    videos, shows = _payload()
    pairs = [(row, virlo._post_id(row, MONITOR, index))
             for index, row in enumerate(videos, start=len(shows))]
    chosen = virlo._pick_set(virlo._reference_groups(videos, shows, _config(), MONITOR),
                             frozenset())[0]

    assert virlo._pick_motion(pairs, chosen, frozenset(ALL_VIDEOS)) is not None
    assert virlo._pick_motion([], chosen, frozenset()) is None
    urlless = [({"id": "vid-x", "views": 9, "author_username": "@a"}, "vid-x")]
    assert virlo._pick_motion(urlless, chosen, frozenset()) is None


def test_fr24_the_three_tiers_are_the_only_tiers_and_each_one_is_logged_by_name() -> None:
    """`motion_tier` is a closed vocabulary — a run whose reels all move alike is explained by this
    field alone, so a fourth spelling would silently break that explanation."""
    tiers = {
        "fresh_same_creator": [STALE, ALSO_USED],
        "fresh": [STALE, ALSO_USED, FRESH_VID_A, FRESH_VID_B],
        "repeat": [STALE, ALSO_USED, *ALL_VIDEOS],
    }
    for expected, used in tiers.items():
        log = _Log()
        _item(used=used, log=log)
        assert log.choice()[1]["motion_tier"] == expected


# --------------------------------------------------------------------------- the public entry point


async def test_fr283_fetch_with_no_monitor_ids_says_so_on_the_console_and_opens_no_session() -> None:
    """`fetch`'s public contract, and the one refusal an operator must not have to find in run.log.

    The short-circuit is what makes this test safe to run offline: it returns before `SessionPool`
    opens, so no MCP subprocess is spawned and no key is read.
    """
    said: list[str] = []
    log = _Log()

    items = await virlo.fetch(_config(virlo_monitor_ids=[]), log=log, used_posts=None,
                              say=said.append)

    assert items == []
    assert len(said) == 1 and "virlo_monitor_ids" in said[0]
    assert "--list-monitors" in said[0]
    assert log.warned("virlo_no_monitors")
