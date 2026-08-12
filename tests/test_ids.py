"""Run ids, slugs and asset ids — the names everything else on disk is filed under.

FR-70 (`run_id` shape), FR-71 (asset-id encoding, the 40-character topic-slug cap, uniqueness
within a run), FR-72/74 (the asset folder IS the asset id), and 20 §3's one normalization
shared by history keys and asset slugs.

These names become Windows paths, so the properties under test are not cosmetic: a slug that
kept a `:` or a `?` is an unwritable folder, and two creatives that collide on an id are one
silently overwritten creative. Everything here is deterministic and file I/O uses `tmp_path`.

**FR-71 post-pivot (v2.0.0):** the id is `<Pl>_<fmt>_<slug>_<NN>` — FOUR segments. The A/B tag
segment is withdrawn with generation mode (operator decision #2): nothing labels a creative
`analyzed` or `direct` any more, and a segment reading `direct` on every folder of every run was
noise inside a name with a MAX_PATH budget. The ordinal stays the TAIL, because §1.10's
provenance block, the ASSIGN receipts and the RENDER lines all name a creative by it.
"""

from __future__ import annotations

import re
from pathlib import Path

from hypesocials.config import Config, PlatformConfig, RunConfig
from hypesocials.models import AssetRecord, PlanEntry, SourcePost, TrendItem
from hypesocials.outputs import AssetFolder, create_run_folder
from hypesocials.plan import assign, build_plan, select
from hypesocials.util import ASSET_SLUG_MAX, new_run_id, slugify

RUN_ID = re.compile(r"^\d{8}_\d{6}_[a-z0-9]{4}$")
ASSET_ID = re.compile(r"^(Li|Ig|Tk)_(img|car|reel)_[a-z0-9][a-z0-9-]*_\d{2,}$")
#: Everything Windows forbids in a path segment, plus whitespace and the separators.
WINDOWS_FORBIDDEN = set('<>:"/\\|?*') | set(chr(c) for c in range(32)) | {" ", "\t"}


# --------------------------------------------------------------------------- builders


def _config(**run_kwargs: object) -> Config:
    # Reuse is deliberately unbounded here: these tests are about the SHAPE of an id, and the
    # FR-8 reuse bound (default 2) would otherwise skip most entries before one is minted.
    run_kwargs.setdefault("max_trend_reuses_per_run", 50)
    cfg = Config(run=RunConfig(**run_kwargs))  # type: ignore[arg-type]
    cfg.platforms = {
        "linkedin": PlatformConfig(formats=["image", "carousel"], carousel_slides=5),
        "instagram": PlatformConfig(formats=["image", "carousel"], carousel_slides=5),
        "tiktok": PlatformConfig(formats=["image", "carousel", "reel"], carousel_slides=5),
    }
    return cfg


def _trend(key: str, name: str, *, strength: float = 0.9, slideshow: bool = False) -> TrendItem:
    """One post-pivot TOPIC item, carrying the one post that keeps it usable under FR-6."""
    return TrendItem(
        history_key=f"m1::{key}",
        monitor_id="m1",
        topic_key=key,
        name=name,
        strength=strength,
        is_slideshow=slideshow,
        why_it_works="hard pattern interrupt in the first frame",
        posts=[SourcePost(post_id=f"{key}-post-1", url="https://www.tiktok.com/@c/video/1",
                          author="c", caption="the hook that stole the week", views=9000)],
    )


def _assigned(cfg: Config, trends: list[TrendItem]) -> list[PlanEntry]:
    """Expand a plan and bind topics to it — the two steps that mint a final asset id."""
    plan = build_plan(cfg)
    assign(plan.entries, select(trends, cfg), cfg)
    return plan.entries


# --------------------------------------------------------------------------- slugify (20 §3)


def test_slugify_is_lowercase_hyphenated_ascii() -> None:
    assert slugify("Dance Challenge") == "dance-challenge"
    assert slugify("AI Audit CTA") == "ai-audit-cta"
    assert slugify("retro   meme --- 2026") == "retro-meme-2026"


def test_slugify_folds_diacritics_instead_of_dropping_the_word() -> None:
    """Czech is a first-class run language (D6), so a Czech trend name must still produce a
    readable key rather than a row of hyphens."""
    assert slugify("Příliš žluťoučký kůň") == "prilis-zlutoucky-kun"
    assert slugify("Malmö Café") == "malmo-cafe"


def test_slugify_is_deterministic_so_two_runs_derive_the_same_history_key() -> None:
    """FR-82's key is `slugify(name)` when no agent id exists; a non-deterministic slug would
    quietly defeat the whole recency window."""
    name = "Retro Meme  Revival!! (2026)"
    assert slugify(name) == slugify(name) == slugify(name.strip())


def test_slugify_output_is_always_a_safe_windows_path_segment() -> None:
    """FR-71: these become folder names under `output/<run_id>/`."""
    hostile = 'CON: "quarterly" report <2026>/Q1\\Q2 | 100%? *now*\n\tsale'
    slug = slugify(hostile, max_len=0)

    assert not (set(slug) & WINDOWS_FORBIDDEN)
    assert re.fullmatch(r"[a-z0-9-]+", slug)
    assert not slug.startswith("-") and not slug.endswith("-")


def test_slugify_degrades_to_untitled_rather_than_an_empty_path_segment() -> None:
    """"Empty or fully non-ASCII input degrades to `untitled`" — an empty segment would make
    `output/<run_id>//meta.yaml`, which is a different (and wrong) path."""
    for pathological in ("", "   ", "!!!", "---", "日本語", "😀😀"):
        assert slugify(pathological) == "untitled"


def test_slugify_caps_at_forty_characters_and_never_ends_on_a_hyphen() -> None:
    """FR-71: "capped at 40 characters for Windows MAX_PATH safety"."""
    assert ASSET_SLUG_MAX == 40
    long_name = "the single most unhinged productivity hack of the entire year"

    capped = slugify(long_name)
    assert len(capped) <= ASSET_SLUG_MAX
    assert not capped.endswith("-")
    assert capped == slugify(long_name)  # the cut is deterministic, not a rolling window

    # the cut is a plain prefix at 40 characters …
    assert slugify("abcdefghij klmnopqrst uvwxyzabcd efghijklm nopq") == \
        "abcdefghij-klmnopqrst-uvwxyzabcd-efghijk"
    # … and a cut landing exactly on a separator drops the dangling hyphen rather than keeping it
    assert slugify("abcdefghij klmnopqrst uvwxyzabcd efghij klmn") == \
        "abcdefghij-klmnopqrst-uvwxyzabcd-efghij"


def test_slugify_max_len_zero_is_the_uncapped_history_key_spelling() -> None:
    """One function, two callers: uncapped for `trend_history.json`, capped inside an asset id."""
    long_name = "a" * 120
    assert len(slugify(long_name, max_len=0)) == 120
    assert len(slugify(long_name)) == ASSET_SLUG_MAX


# --------------------------------------------------------------------------- run_id (FR-70)


def test_fr70_run_id_shape() -> None:
    """FR-70: "`YYYYMMDD_HHMMSS_<4-char-random>`. Example: `20260808_143022_x7q2`"."""
    run_id = new_run_id()

    assert RUN_ID.fullmatch(run_id), run_id
    assert len(run_id) == 20  # 8 date + 1 + 6 time + 1 + 4 random
    assert not (set(run_id) & WINDOWS_FORBIDDEN)
    assert RUN_ID.fullmatch("20260808_143022_x7q2")  # the PRD's own example


def test_fr70_run_ids_launched_in_the_same_second_do_not_collide() -> None:
    """"the random suffix is what keeps two runs launched in the same second from colliding"."""
    ids = [new_run_id() for _ in range(200)]
    stamps = {run_id[:15] for run_id in ids}
    suffixes = {run_id[16:] for run_id in ids}

    assert len(stamps) <= 2  # generated inside one or two clock seconds
    assert len(suffixes) > 100  # 36^4 of entropy: near-total distinctness, no exact-count flake
    assert len(set(ids)) >= 195


# --------------------------------------------------------------------------- asset_id (FR-71)


def test_fr71_asset_id_encodes_platform_format_slug_and_ordinal() -> None:
    """FR-71 as amended v2.0.0: "asset_id encodes: platform (Li, Ig, Tk), format (img, car, reel),
    a URL-safe slug of the source topic name …, and a zero-padded per-run ordinal".

    FOUR segments, not five. The variant tag is withdrawn with A/B mode, and the ordinal is the
    TAIL: §1.10's provenance block, the ASSIGN receipts and the per-job RENDER lines all shorten a
    creative to `asset_id.rsplit("_", 1)[-1]`, so anything appended after it breaks that read.
    """
    cfg = _config(formats={"image": 3, "carousel": 2, "reel": 0})
    entries = _assigned(cfg, [_trend("dance", "Dance Challenge", slideshow=True)])

    for entry in entries:
        assert ASSET_ID.fullmatch(entry.asset_id), entry.asset_id
        platform, fmt, slug, ordinal = entry.asset_id.split("_")
        assert platform == {"linkedin": "Li", "instagram": "Ig", "tiktok": "Tk"}[entry.platform]
        assert fmt == {"image": "img", "carousel": "car", "reel": "reel"}[entry.creative_format]
        assert slug == "dance-challenge"
        assert int(ordinal) == entry.order + 1 and len(ordinal) >= 2
        assert entry.asset_id.rsplit("_", 1)[-1] == ordinal  # the console's short handle

    assert ASSET_ID.fullmatch("Li_car_dance-challenge_02")  # the PRD's own example, post-pivot
    assert not ASSET_ID.fullmatch("Li_car_dance-challenge_analyzed_02"), \
        "the withdrawn variant segment must not be accepted back in by a lax pattern"


def test_fr71_ids_are_unique_within_a_run_even_when_everything_else_matches() -> None:
    """FR-71: "two creatives sharing platform + format + topic receive distinct ordinals to
    prevent silent folder overwrites". The variant tag used to add a second axis of distinctness;
    with it withdrawn the ordinal is the ONLY thing keeping these six folders apart."""
    cfg = _config(formats={"image": 6, "carousel": 0, "reel": 0}, platforms=["linkedin"],
                  languages={"linkedin": "en"})
    cfg.platforms = {"linkedin": PlatformConfig(formats=["image", "carousel"])}
    entries = _assigned(cfg, [_trend("dance", "Dance Challenge")])

    ids = [entry.asset_id for entry in entries]
    assert len(ids) == 6
    assert len(set(ids)) == 6
    # everything but the ordinal is identical, which is exactly the collision case
    assert {id_.rsplit("_", 1)[0] for id_ in ids} == {"Li_img_dance-challenge"}
    assert [id_.rsplit("_", 1)[1] for id_ in ids] == ["01", "02", "03", "04", "05", "06"]


def test_fr71_the_topic_slug_inside_an_id_is_capped_and_windows_safe() -> None:
    """A 90-character topic name with punctuation still has to make a writable folder name."""
    hostile = 'The "Unhinged" Productivity Hack: 10x Your Output <in 2026> — Přílišně | Ještě?'
    cfg = _config(formats={"image": 1, "carousel": 0, "reel": 0})
    entries = _assigned(cfg, [_trend("hack", hostile)])

    asset_id = entries[0].asset_id
    slug = asset_id.split("_")[2]
    assert len(slug) <= ASSET_SLUG_MAX
    assert not (set(asset_id) & WINDOWS_FORBIDDEN)
    assert ASSET_ID.fullmatch(asset_id), asset_id


def test_fr71_an_unassigned_entry_still_carries_a_usable_provisional_id() -> None:
    """The plan is logged and budgeted before Collect runs, so an id exists before a topic does —
    it is rewritten in place once `assign()` binds one."""
    cfg = _config(formats={"image": 2, "carousel": 0, "reel": 0})
    plan = build_plan(cfg)

    assert all(ASSET_ID.fullmatch(entry.asset_id) for entry in plan.entries)
    assert all(entry.asset_id.split("_")[2] == "unassigned" for entry in plan.entries)

    assign(plan.entries, select([_trend("dance", "Dance Challenge")], cfg), cfg)
    assert all(entry.asset_id.split("_")[2] == "dance-challenge" for entry in plan.entries)


def test_fr71_a_brief_creative_takes_its_slug_from_the_brief_name() -> None:
    """40 §2: brief-driven creatives (override, no topic) get a "slug derived from the brief
    name" — `assign()` leaves them alone because they consume no topic (FR-144)."""
    from hypesocials.models import Brief
    from hypesocials.plan import BriefRequest

    cfg = _config(formats={"image": 0, "carousel": 0, "reel": 0})
    brief = Brief(name="AI Audit CTA", description="d", influence="override", formats=["image"])
    plan = build_plan(cfg, briefs=[BriefRequest(brief=brief, count=2)])
    assign(plan.entries, select([_trend("dance", "Dance Challenge")], cfg), cfg)

    assert [entry.asset_id.split("_")[2] for entry in plan.entries] == ["ai-audit-cta"] * 2
    assert all(entry.trend_key is None for entry in plan.entries)


# --------------------------------------------------------------------------- ids on disk


def test_fr71_the_asset_folder_name_is_the_asset_id_verbatim(tmp_path: Path) -> None:
    """40 §1: "one subdirectory per generated creative uses the naming scheme `<asset_id>/`".
    The packager never re-derives an id — `plan.py` is FR-71's single producer."""
    run_dir = create_run_folder(tmp_path, "20260808_143022_x7q2")
    assert run_dir == tmp_path / "20260808_143022_x7q2"
    assert (run_dir / "refs").is_dir()  # FR-71's shared per-run reference folder

    folder = AssetFolder(run_dir, AssetRecord(
        asset_id="Li_car_dance-challenge_02", source="dance",
        source_name="Dance Challenge", platform="linkedin", creative_format="carousel"))

    assert folder.path == run_dir / "Li_car_dance-challenge_02"
    assert folder.path.is_dir()
    assert (folder.path / "meta.yaml").is_file()  # NFR-21: never media without meta


def test_fr71_distinct_ordinals_make_distinct_folders_and_never_overwrite(
    tmp_path: Path,
) -> None:
    """The reason the ordinal exists: same platform + format + topic, two folders."""
    run_dir = create_run_folder(tmp_path, new_run_id())
    ids = ["Li_img_dance-challenge_01", "Li_img_dance-challenge_02"]

    for asset_id in ids:
        folder = AssetFolder(run_dir, AssetRecord(
            asset_id=asset_id, source="dance", source_name="Dance Challenge",
            platform="linkedin", creative_format="image"))
        folder.write_caption(f"caption for {asset_id}")

    assert sorted(p.name for p in run_dir.iterdir() if p.is_dir()) == [*ids, "refs"]
    for asset_id in ids:
        assert asset_id in (run_dir / asset_id / "caption.txt").read_text(encoding="utf-8")
