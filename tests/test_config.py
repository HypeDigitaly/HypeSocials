"""`hypesocials.config` — loading, defaulting and the one-line refusal (FR-50/51/69, NFR-15/19).

Every test drives the module's PUBLIC API only (`load_config`, `list_configs`, `Config`,
`ConfigError`); the private builders are exercised through it. All file I/O is in `tmp_path`,
except the two read-only assertions that the shipped `configs/*.yaml` still load.

The invariant behind most of these: a config file is *data*, so an absent key must default
(FR-50/NFR-19) and a malformed key must produce exactly ONE operator-facing line naming the key
and the expected shape (FR-51/69) — never a traceback, never a partial load.

The tail section covers the flags that override this same surface for one run (FR-61/137/299):
they live here because what they change — and never rewrite — is a config. `--sources` is
deliberately NOT among them: it is a dead FR-135 remnant scheduled for deletion, and a test for
it would freeze a corpse. `--mode` is already gone (A/B mode withdrawn, v2.0.0) and is asserted
gone rather than exercised.

The withdrawn pre-pivot keys (`run.generation_mode`, `sources.inspiration_mix` and friends)
left the schema at Wave 3.5 and now load as unknown-key WARNINGS — the desired end state the
migration promised. Tests below assert what the loader does today and
are expected to be deleted with the keys.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from hypesocials import cli
from hypesocials.config import (
    CONFIGS_DIR,
    Config,
    ConfigError,
    RunConfig,
    list_configs,
    load_config,
)

# --------------------------------------------------------------------------- helpers


def write(folder: Path, text: str, name: str = "unit.yaml") -> Path:
    """Put one config file in `folder` and return its path."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def load(folder: Path, text: str, name: str = "unit.yaml") -> Config:
    write(folder, text, name)
    return load_config(Path(name).stem, configs_dir=folder)


def refusal(folder: Path, text: str) -> str:
    """Load a config expected to fail and return the single operator-facing line."""
    write(folder, text)
    with pytest.raises(ConfigError) as caught:
        load_config("unit", configs_dir=folder)
    message = str(caught.value)
    assert "\n" not in message, f"FR-69 wants exactly one line, got:\n{message}"
    return message


# --------------------------------------------------------------------------- valid load


def test_fr50_a_valid_file_loads_and_absent_keys_take_their_documented_defaults(
    tmp_path: Path,
) -> None:
    """FR-50: "applying documented defaults for any key absent from that file"."""
    cfg = load(tmp_path, "run:\n  spend_cap_usd: 3.5\n  carousel_anchor: true\n")

    assert cfg.run.spend_cap_usd == 3.5
    assert cfg.run.carousel_anchor is True
    # untouched keys — the defaults 30 §2 documents
    assert cfg.run.trend_history_days == 30  # v2.1.0 (FR-307): was 7, now covers the fetch window
    # v2.2.0 (D49): 25 -> 45 (D48: 600 s jobs + the FR-317 resubmit) -> 60, which additionally has
    # to hold up to `run.gauntlet.rounds_max` re-render rounds after that worst case.
    assert cfg.run.run_deadline_min == 60
    assert cfg.sources.active == ["virlo"]
    assert cfg.models.analysis == "anthropic/claude-sonnet-5"
    assert cfg.output.dir == "output/"
    assert cfg.name == "unit" and cfg.path.name == "unit.yaml"


def test_fr50_defaults_applied_names_every_key_that_fell_back(tmp_path: Path) -> None:
    """"`defaults_applied` naming the keys that fell back" — the run log's honesty line."""
    cfg = load(tmp_path, "run:\n  spend_cap_usd: 3.5\n")

    assert "run.gauntlet" in cfg.defaults_applied
    assert "sources" in cfg.defaults_applied  # the whole block was absent
    assert "run.spend_cap_usd" not in cfg.defaults_applied
    assert cfg.warnings == ()


def test_nfr19_an_empty_file_loads_as_a_full_default_config(tmp_path: Path) -> None:
    """NFR-19: "any file predating the new key continues to load successfully using that key's
    documented default" — the limit case is a file that predates every key."""
    cfg = load(tmp_path, "# nothing but a comment\n")

    assert cfg.run.formats == {"image": 0, "carousel": 6, "reel": 0}  # v2.1.0 §0.3: all-carousels
    assert cfg.run.text_budgets.image_headline == 90  # v2.1.0 §0.5: was 42
    assert cfg.platforms  # per-platform defaults are built even with no platforms: block
    assert cfg.description == "nothing but a comment"  # FR-173 picker line


def test_nfr19_a_partial_mapping_merges_key_by_key_instead_of_replacing_it(
    tmp_path: Path,
) -> None:
    """30 §1: "a variant lists only what it overrides". Naming one format must not delete the
    other two, or a niche file would silently zero the run.

    The named format is `carousel` rather than `image` since v2.1.0: an image count over a
    slideshow-only source is refused outright (§0.14e, its own test below), so overriding it here
    would test the guard instead of the merge.
    """
    cfg = load(tmp_path,
               "run:\n  formats: { carousel: 1 }\n  text_budgets:\n    image_headline: 30\n")

    assert cfg.run.formats == {"image": 0, "carousel": 1, "reel": 0}
    assert cfg.run.text_budgets.image_headline == 30
    assert cfg.run.text_budgets.image_subline == 160  # untouched sibling keeps its default
    assert "run.text_budgets.image_subline" in cfg.defaults_applied


def test_fr292_a_partial_brand_profile_override_keeps_the_compiled_profile_around_it(
    tmp_path: Path,
) -> None:
    """The same key-by-key promise as the test above, one level deeper (FR-292, plan §1.4: the
    compiled profiles are "all overridable").

    The default side of THIS merge is a dataclass instance sitting inside a mapping, not a mapping,
    so a whole-entry replacement is the natural failure: overriding one colour would blank the
    wordmark, the fonts and both `never:` lists. A branded render would then sign itself with an
    empty string and lose the colour guards it renders under — silently, in paid output.
    """
    cfg = load(tmp_path, "branding:\n  brand: hypelead\n  profiles:\n"
                         "    hypelead:\n      colors: { teal_bright: '#123456' }\n")

    profile = cfg.branding.profiles["hypelead"]
    assert profile.colors["teal_bright"] == "#123456"  # the override takes
    assert profile.colors["teal_deep"] == "#0A7F78"  # its sibling colours survive
    assert profile.wordmark == "HypeLead"  # and so does every field the file never mentioned
    assert profile.fonts == {"primary": "Geist", "mono": "Geist Mono"}
    assert profile.never_style == ["no photography/stock/3D", "no serif or handwritten type",
                                   "teal is accent only, never full-bleed canvas"]
    assert profile.never_always and profile.product_nouns == ["HypeLead"]
    assert cfg.branding.profiles["hypedigitaly"].wordmark == "HypeDigitaly"  # untouched profile


def test_fr132_platform_defaults_are_per_platform_not_shared(tmp_path: Path) -> None:
    """30 §2: image + carousel everywhere, reel allowlisted on TikTok only.

    The slide max is per-platform too since 2026-08-13, and for the same reason the format
    allowlist is: it states what the DESTINATION accepts (Instagram stops at 10, the others take
    20), not a house preference. `configs/hypedigitaly.yaml` ships no `platforms:` block at all,
    so a shared number here would silently truncate every deck on the operator's real config.
    """
    cfg = load(tmp_path, "run:\n  platforms: [linkedin, tiktok, instagram]\n")

    assert cfg.platform("linkedin").formats == ["image", "carousel"]
    assert cfg.platform("tiktok").formats == ["image", "carousel", "reel"]
    assert cfg.platform("linkedin").carousel_slides == 20
    assert cfg.platform("tiktok").carousel_slides == 20
    assert cfg.platform("instagram").carousel_slides == 10  # the platform's own hard ceiling
    assert cfg.platform("mastodon").formats == ["image", "carousel"]  # unnamed platform defaults
    assert cfg.platform("mastodon").carousel_slides == 10  # ... at the safe generic max


def test_the_shipped_configs_all_load_without_an_error() -> None:
    """The picker offers these; a shipped file that refuses to load would be a broken product."""
    summaries = list_configs()
    assert {s.name for s in summaries} >= {"default", "hypedigitaly"}
    for summary in summaries:
        cfg = load_config(summary.name)
        assert cfg.name == summary.name
        assert cfg.path == summary.path


# --------------------------------------------------------------------------- malformed input


def test_fr69_invalid_yaml_produces_one_line_naming_the_file_and_the_place(
    tmp_path: Path,
) -> None:
    """FR-69: "exactly one plain-English error line identifying the offending key or flag"."""
    line = refusal(tmp_path, "run:\n  formats: { image: 4\n  spend_cap_usd: 2\n")

    assert line.startswith("unit.yaml")
    assert "not valid YAML" in line
    assert "line" in line  # the parser's mark, so the operator can go straight there


def test_fr69_a_top_level_scalar_is_not_a_config(tmp_path: Path) -> None:
    line = refusal(tmp_path, "just a string\n")
    assert line == "unit.yaml: expected a mapping of settings at the top level"


def test_fr69_a_wrong_typed_scalar_names_the_key_the_value_and_the_expected_shape(
    tmp_path: Path,
) -> None:
    line = refusal(tmp_path, "run:\n  spend_cap_usd: ten dollars\n")

    assert "run.spend_cap_usd" in line
    assert "'ten dollars'" in line
    assert "a positive number of dollars" in line


def test_fr69_a_wrong_typed_boolean_names_true_or_false(tmp_path: Path) -> None:
    line = refusal(tmp_path, "run:\n  carousel_anchor: maybe\n")
    assert "run.carousel_anchor" in line and "expected true or false" in line


def test_fr69_a_value_outside_a_closed_vocabulary_lists_the_options(tmp_path: Path) -> None:
    # W3.5 re-base: `generation_mode` left the schema, so another Literal key carries the check.
    line = refusal(tmp_path, "run:\n  reel_overlay_text: painted\n")
    assert "run.reel_overlay_text" in line
    assert "seed_frame | in_model | none" in line


def test_fr69_a_scalar_where_a_block_belongs_says_so(tmp_path: Path) -> None:
    line = refusal(tmp_path, "sources: virlo\n")
    assert "sources" in line and "a mapping of key: value pairs" in line


def test_fr69_a_scalar_where_a_list_belongs_says_so(tmp_path: Path) -> None:
    line = refusal(tmp_path, "sources:\n  active: virlo\n")
    assert "sources.active" in line and "expected a list" in line


def test_fr69_an_out_of_range_number_names_the_range(tmp_path: Path) -> None:
    line = refusal(tmp_path, "models:\n  poll_interval_s: 900\n")
    assert "models.poll_interval_s" in line and "1–60" in line


def test_fr69_an_unknown_source_adapter_is_refused_by_name(tmp_path: Path) -> None:
    line = refusal(tmp_path, "sources:\n  active: [virlo, reddit]\n")
    assert "sources.active" in line and "reddit" in line


def test_fr69_an_unknown_platform_is_refused_by_name_rather_than_silently_spent_on(
    tmp_path: Path,
) -> None:
    """D6 fixes the platform set, so `linkedn` is malformed — and it used to load clean: nothing
    is ever planned for it, while its correctly-spelled siblings still spend the whole budget."""
    line = refusal(tmp_path, "run:\n  platforms: [linkedn, tiktok]\n")

    assert "run.platforms" in line and "'linkedn'" in line
    assert "linkedin | instagram | tiktok" in line


def test_fr69_an_unknown_language_names_the_platform(tmp_path: Path) -> None:
    line = refusal(tmp_path, "run:\n  languages: { linkedin: de }\n")
    assert "linkedin" in line and "en | cs" in line


def test_fr69_a_negative_price_is_malformed_but_null_is_a_legitimate_unpriced(
    tmp_path: Path,
) -> None:
    """FR-282: "`null` means *unpriced* and prints as such — it is never treated as free";
    a negative rate is not a price at all."""
    line = refusal(
        tmp_path, "models:\n  price_per_unit:\n    image: { '1k': -0.03 }\n")
    assert "models.price_per_unit.image.1k" in line and "non-negative price" in line

    cfg = load(tmp_path, "models:\n  price_per_unit:\n    image: { '1k': null }\n")
    assert cfg.models.price_per_unit.image["1k"] is None
    assert cfg.models.price_per_unit.image["2k"] == 0.05  # siblings keep their real defaults


def test_a_missing_config_file_names_what_was_sought_and_what_exists(tmp_path: Path) -> None:
    write(tmp_path, "run: {}\n", "present.yaml")
    with pytest.raises(ConfigError) as caught:
        load_config("absent", configs_dir=tmp_path)
    line = str(caught.value)
    assert "absent.yaml" in line and "present.yaml" in line and "\n" not in line


def test_d30_a_dollar_brace_placeholder_is_a_hard_error_at_any_depth(tmp_path: Path) -> None:
    """D30/FR-130: config loading has NO interpolation, which is what keeps a config file
    secret-free; a placeholder that silently stayed literal would be a leak waiting to happen."""
    line = refusal(
        tmp_path, "mcp_servers:\n  virlo:\n    env: { VIRLO_API_KEY: '${VIRLO_API_KEY}' }\n")
    assert "${...}" in line
    assert "mcp_servers.virlo.env.VIRLO_API_KEY" in line
    assert ".env" in line

    nested = refusal(tmp_path, "sources:\n  inspiration_folders: ['${HOME}/pics']\n")
    assert "sources.inspiration_folders[0]" in nested


def test_fr51_an_unknown_key_warns_and_is_ignored_rather_than_refusing(tmp_path: Path) -> None:
    """A typo must not cost the whole run: unknown keys are warnings, malformed values are not."""
    cfg = load(tmp_path, "run:\n  spend_cap_usd: 2\n  carousel_anchr: true\nnonsense: 1\n")

    assert any("run.carousel_anchr" in w for w in cfg.warnings)
    assert any("nonsense" in w for w in cfg.warnings)
    assert cfg.run.carousel_anchor is True  # the real key kept its default


def test_nfr111_a_token_cap_under_its_floor_is_clamped_up_with_a_warning(tmp_path: Path) -> None:
    """NFR-111: below the floor a cap buys truncation retries instead of saving money."""
    cfg = load(tmp_path, "models:\n  max_tokens: { analysis: 50 }\n")

    assert cfg.max_tokens_for("analysis") == cfg.models.max_tokens_floor["analysis"]
    assert any("max_tokens.analysis" in w and "clamped" in w for w in cfg.warnings)

    line = refusal(
        tmp_path,
        "models:\n  max_tokens: { analysis: 0 }\n  max_tokens_floor: { analysis: 0 }\n")
    assert "max_tokens_floor.analysis" in line


def test_f5_the_critic_role_bounds_its_reasoning_at_low_by_default(tmp_path: Path) -> None:
    """Session 5.5/F5: an absent key means the critic thinks at `low`, not unbidden at full effort.

    Sending no `reasoning` field is not a saving — Sonnet-5 then thinks at its own default and
    bills every token inside `completion_tokens`, which is what cost the Session 5 acceptance run
    $1.30 of critic spend the pre-flight never quoted. So the bound lives in code and applies to
    configs written before the key existed (NFR-19); the file may still raise it, and a value the
    provider would reject is refused at load rather than at spend time (FR-69).
    """
    assert Config().models.critic_reasoning_effort == "low"
    assert load(tmp_path, "run: {}\n").models.critic_reasoning_effort == "low"
    assert load(tmp_path,
                "models:\n  critic_reasoning_effort: medium\n"
                ).models.critic_reasoning_effort == "medium"
    # ... and the COPY role's own knob is untouched by it (30 §2: two roles, two rows).
    assert Config().models.reasoning_effort == "low"

    line = refusal(tmp_path, "models:\n  critic_reasoning_effort: maximum\n")
    assert "models.critic_reasoning_effort" in line and "low | medium | high" in line


def test_fr131_reels_requested_without_a_price_warn_rather_than_fail_the_load(
    tmp_path: Path,
) -> None:
    """10 §10: "Reels are not planned at all; the menu reports the missing price" — the config
    still loads, because the drop happens at pre-flight, not here.

    Every reel config here also sets `sources.include_videos: true`: since v2.1.0 a reel count over
    slideshow-only sourcing is a load refusal (§0.14e), and this test is about the PRICE, not that
    guard — so the file states the sourcing a reel run genuinely needs.
    """
    reels = "run:\n  formats: { reel: 2 }\nsources:\n  include_videos: true\n"
    cfg = load(tmp_path, reels)

    assert cfg.reels_plannable is False
    assert cfg.reel_price_key == "models.price_per_unit.reel_second.720p"
    assert any("reel_second" in w for w in cfg.warnings)

    priced = load(tmp_path, reels
                  + "models:\n  price_per_unit:\n    reel_second: { '720p': 0.19 }\n")
    assert priced.reels_plannable is True
    assert priced.reel_price_per_second == 0.19


def test_a_run_deadline_under_the_video_job_timeout_warns_on_a_reel_capable_config(
    tmp_path: Path,
) -> None:
    """Operator decision 2026-08-10: `video_job_timeout_s` is 30 min because the W6 run threw away
    a paid reel at 600 s (a timed-out job is never resubmitted, 20 §8). A 25-min deadline would
    abandon the run before that ceiling could ever fire, so the pairing is warned about — but only
    where reels are actually reachable, otherwise every default load would carry the noise."""
    assert Config().models.video_job_timeout_s == 1800

    priced = "models:\n  price_per_unit:\n    reel_second: { '720p': 0.95 }\n"
    # v2.1.3 (D48) raised the deadline default to 45 min (2700 s > 1800 s) and v2.2.0/D49 to 60,
    # so the tight pairing must now be written explicitly to reproduce the warned shape.
    warned = load(tmp_path, "run:\n  run_deadline_min: 25\n" + priced)  # 1500 s < 1800 s
    assert any("run_deadline_min" in w and "video_job_timeout_s" in w for w in warned.warnings)

    # The quiet case is the SHIPPED deadline: at 45 the video pairing is already quiet, but the
    # carousel-throughput advisory (which names `run_deadline_min` too) fires, so the assertion
    # below is scoped to the pairing this test is about rather than to the key's name alone.
    quiet = load(tmp_path, "run:\n  run_deadline_min: 60\n" + priced)
    assert not any("video_job_timeout_s" in w for w in quiet.warnings)
    # Reels unreachable (default.yaml's shape): the VIDEO pairing stays silent. (A 25-min
    # deadline under 600 s image jobs now earns the separate carousel-throughput advisory,
    # which is that function's own concern — asserted in its own tests.)
    assert not any("video_job_timeout_s" in w
                   for w in load(tmp_path, "run:\n  run_deadline_min: 25\n").warnings)


# ------------------------------------------------- D46: the fetch window and its two invariants


def test_fr170_the_v2_1_0_sourcing_and_budget_defaults_are_the_ones_30_section_2_documents(
    tmp_path: Path,
) -> None:
    """The D46 defaults, asserted where an operator would look them up (30 §2, FR-170/259/280).

    They are asserted together because they are one decision: v1 fetches recent SLIDESHOWS
    (`include_videos: false`, 3 pages, 30 days), reads their slides (`vision_transcribe`), quotes
    the panels verbatim under budgets wide enough to hold a real panel, and renders them without a
    reference image (`models.image` on the text-to-image route). Any one of these silently reverted
    puts the run back to the behaviour the operator rejected on 2026-08-13.
    """
    cfg = load(tmp_path, "run: {}\n")

    assert cfg.sources.include_videos is False  # slideshows only (FR-301, §0.2)
    assert cfg.sources.fetch_pages == 3
    assert cfg.sources.max_post_age_days == 30
    assert cfg.sources.vision_transcribe is True  # FR-306, §0.11
    # FR-50: a file that names one of the new keys still reports the siblings it left out.
    partial = load(tmp_path, "sources:\n  fetch_pages: 5\n")
    assert partial.sources.fetch_pages == 5
    assert "sources.include_videos" in partial.defaults_applied
    assert "sources.fetch_pages" not in partial.defaults_applied

    budgets = cfg.run.text_budgets
    assert (budgets.image_headline, budgets.image_subline) == (90, 160)
    assert budgets.slide == 300  # NEW key: per-slide deck text on panel-mapped carousels (FR-304)
    assert (budgets.reel_seed_headline, budgets.retry_reduction_pct) == (60, 40)

    # FR-280: the reference-FREE route is the default; the profile keeps the i2i sibling for the
    # jobs that genuinely carry a reference (brief image, carousel anchor, reel seed frame).
    assert cfg.models.image == "gpt-image-2-text-to-image"


def test_fr285_the_fetch_window_keys_are_refused_out_of_range_rather_than_clamped_into_it(
    tmp_path: Path,
) -> None:
    """FR-285/FR-138: "refused-not-clamped". A fetch window silently corrected into range would
    change which posts a paid run quotes without ever telling the operator it did so."""
    assert "1–10" in refusal(tmp_path, "sources:\n  fetch_pages: 0\n")
    assert "sources.fetch_pages" in refusal(tmp_path, "sources:\n  fetch_pages: 11\n")

    line = refusal(tmp_path, "sources:\n  max_post_age_days: 400\n")
    assert "sources.max_post_age_days" in line and "0–365" in line

    # A slide budget is bounded like its siblings, one shared range (FR-259).
    assert "1–400" in refusal(tmp_path, "run:\n  text_budgets: { slide: 0 }\n")

    # In-range values load, including the documented "off" ends of both windows.
    wide = load(tmp_path, "sources:\n  fetch_pages: 10\n  max_post_age_days: 0\n")
    assert (wide.sources.fetch_pages, wide.sources.max_post_age_days) == (10, 0)


def test_fr307_a_history_window_narrower_than_the_fetch_window_is_refused_naming_both_keys(
    tmp_path: Path,
) -> None:
    """FR-307: the no-repeat memory must cover at least the window the fetch reaches back over.

    Under a 7-day memory and a 30-day fetch there is a three-week band where a post is forgotten by
    history and still returned by Virlo — so the run re-quotes, word for word, what it published
    last week. Both keys are legal alone, so the refusal has to name both and both values, and it
    must be a refusal rather than a clamp: raising the memory and narrowing the fetch are different
    decisions with different costs, and neither is the engine's to make.
    """
    line = refusal(tmp_path, "run:\n  trend_history_days: 7\nsources:\n  max_post_age_days: 30\n")

    assert "run.trend_history_days" in line and "sources.max_post_age_days" in line
    assert "7" in line and "30" in line
    assert "FR-307" in line

    # Equal is the shipped pairing and passes; wider memory than fetch window passes too.
    assert load(tmp_path, "run: {}\n").run.trend_history_days == 30
    assert load(tmp_path, "run:\n  trend_history_days: 90\n").run.trend_history_days == 90

    # `0` is the operator's explicit opt-out — the window is OFF, not half-covering the fetch.
    off = load(tmp_path, "run:\n  trend_history_days: 0\nsources:\n  max_post_age_days: 30\n")
    assert off.run.trend_history_days == 0 and off.warnings == ()


def test_d46_014e_image_and_reel_counts_are_refused_while_sourcing_is_slideshow_only(
    tmp_path: Path,
) -> None:
    """§0.14e/FR-132: with `include_videos: false` every topic is slideshow-majority, and only a
    carousel can quote a slideshow panel for panel (FR-304). An image or reel planned against that
    pool would rank-fallback onto a post it cannot use properly — silently, every run, forever — so
    the pair is refused and the operator picks which half to change."""
    line = refusal(tmp_path, "run:\n  formats: { image: 2, carousel: 4, reel: 1 }\n")

    assert "run.formats" in line and "sources.include_videos" in line
    assert "2 image" in line and "1 reel" in line  # both offending counts, not just the first
    assert "carousel" not in line.split("—")[0]  # carousels are never the thing being refused

    # The two documented cures, both loading clean.
    carousels_only = load(tmp_path, "run:\n  formats: { image: 0, carousel: 6, reel: 0 }\n")
    assert carousels_only.run.formats == {"image": 0, "carousel": 6, "reel": 0}

    with_video = load(tmp_path, "run:\n  formats: { image: 2, carousel: 4, reel: 1 }\n"
                                "sources:\n  include_videos: true\n")
    assert with_video.run.formats["image"] == 2 and with_video.sources.include_videos is True


# ------------------------------------------------------- FR-314: the style selector (v2.1.2/D-E)


def test_fr314_the_styles_selector_parses_and_an_absent_block_means_every_style(
    tmp_path: Path,
) -> None:
    """`styles.enabled` is a list of registry KEYS, and its empty default means "all of them".

    That default is the whole compatibility story of FR-314: every config written before the key
    existed — and `configs/default.yaml`, which ships it empty — must keep rotating over the full
    registry. So absence is recorded in `defaults_applied` like any other defaulted key, never
    read as "this run selected nothing".
    """
    chosen = load(tmp_path, "styles:\n  enabled: [alpha, beta]\n")
    assert chosen.styles.enabled == ["alpha", "beta"]  # order is the file's, and it is kept

    absent = load(tmp_path, "run:\n  spend_cap_usd: 3.5\n")
    assert absent.styles.enabled == []
    assert "styles" in absent.defaults_applied  # the whole block fell back

    explicit_empty = load(tmp_path, "styles:\n  enabled: []\n")
    assert explicit_empty.styles.enabled == []
    assert "styles.enabled" not in explicit_empty.defaults_applied  # the file did write it


def test_fr314_a_selector_that_is_not_a_list_of_strings_is_one_refusal_line(
    tmp_path: Path,
) -> None:
    """FR-51/69 posture, unchanged by the new key: name the key, the value and the shape wanted.

    A bare scalar is the mistake worth catching — `enabled: brand-card` reads perfectly to a human
    and would otherwise become the six-character-membership test `"b" in "brand-card"`, i.e. a
    selection nobody wrote.
    """
    scalar = refusal(tmp_path, "styles:\n  enabled: brand-card\n")
    assert "styles.enabled" in scalar and "a list" in scalar

    numeric = refusal(tmp_path, "styles:\n  enabled: [alpha, 7]\n")
    assert "styles.enabled[1]" in numeric and "text" in numeric


def test_fr314_a_stale_refs_per_job_key_warns_and_the_run_still_loads(tmp_path: Path) -> None:
    """The D46/F3 tombstone survives FR-314's revival of the `styles:` block: `refs_per_job` was a
    reference-image window, a text-only style has none, and an operator file that still carries it
    must load with the ordinary unknown-key WARNING rather than refuse. Reviving the section is not
    reviving its dead key."""
    cfg = load(tmp_path, "styles:\n  enabled: [alpha]\n  refs_per_job: 2\n")

    assert cfg.styles.enabled == ["alpha"]
    assert any("styles.refs_per_job" in warning for warning in cfg.warnings), cfg.warnings
    assert not hasattr(cfg.styles, "refs_per_job")


# ------------------------------------------- FR-336: matched style assignment (v2.4.0/D56)


def test_fr336_the_assignment_knob_parses_defaults_to_rotation_and_refuses_anything_else(
    tmp_path: Path,
) -> None:
    """`styles.assignment` chooses WHICH ALGORITHM assigns a style at all (FR-334/336).

    The default is `rotation` and it is a DEFAULT, not a fallback: FR-291 stays the invariant
    substrate for every config written before the key existed (NFR-19), and switching back to it
    restores pre-D56 behaviour byte-exactly. `matched` is the opt-in that costs an LLM call, which
    is why a typo may not silently land on either value — it is refused at LOAD, in one
    operator-facing line naming the key and both accepted words (FR-51/69), so the mistake costs
    exit 2 and $0 rather than a run assigned by an algorithm nobody chose.
    """
    assert Config().styles.assignment == "rotation", "the dataclass default"
    assert load(tmp_path, "run: {}\n").styles.assignment == "rotation", "an absent block"

    for word in ("rotation", "matched"):
        cfg = load(tmp_path, f"styles:\n  assignment: {word}\n")
        assert cfg.styles.assignment == word and isinstance(cfg.styles.assignment, str)

    # A file that writes a sibling key still reports this one as defaulted (FR-50's honesty line).
    partial = load(tmp_path, "styles:\n  enabled: [alpha]\n")
    assert partial.styles.assignment == "rotation"
    assert "styles.assignment" in partial.defaults_applied
    assert "styles.enabled" not in partial.defaults_applied

    line = refusal(tmp_path, "styles:\n  assignment: banana\n")
    assert "styles.assignment" in line and "'banana'" in line
    assert "rotation | matched" in line, "the refusal has to name what IS accepted"


def test_fr336_the_two_dials_in_the_styles_block_share_half_a_vocabulary_and_stay_independent(
    tmp_path: Path,
) -> None:
    """THE trap in this block, pinned deliberately: `styles.rotation` (`seeded | fixed`, D52) and
    `styles.assignment` (`rotation | matched`, D56) are different questions whose value
    vocabularies OVERLAP on the word "rotation".

    `rotation` chooses where the deterministic scan STARTS; `assignment` chooses whether that scan
    is the final answer or only the baseline an LLM matcher may overrule — and `assignment:
    rotation` still obeys `rotation: seeded | fixed` underneath it. A loader that conflated them
    would look completely correct on the shipped configs (all three pin `matched` + `seeded`) and
    would silently pin the rotation offset at 0, or silently switch the matcher off, on the one
    config that asked for the other pairing.

    So all four pairings are asserted to load as written, and each key is asserted to REFUSE the
    other's vocabulary — which is what makes a copy-paste between the two lines a one-line refusal
    instead of a run that quietly did something else.
    """
    for assignment in ("rotation", "matched"):
        for start in ("seeded", "fixed"):
            cfg = load(tmp_path,
                       f"styles:\n  assignment: {assignment}\n  rotation: {start}\n")
            assert (cfg.styles.assignment, cfg.styles.rotation) == (assignment, start)
            assert cfg.warnings == (), "both are known keys; neither is a typo of the other"

    swapped = refusal(tmp_path, "styles:\n  assignment: seeded\n")
    assert "styles.assignment" in swapped and "rotation | matched" in swapped

    other_way = refusal(tmp_path, "styles:\n  rotation: matched\n")
    assert "styles.rotation" in other_way and "seeded | fixed" in other_way


def test_fr336_the_three_shipped_brand_configs_pin_matched_and_default_yaml_does_not() -> None:
    """D56's shipped posture, read off the files that actually ship (§2 decision 6).

    The three brand configs are the operator's own runs and they opt IN — matched assignment is
    what keeps the 17-key `styles.enabled` set coherent, since seventeen styles under plain
    rotation is visual chaos. `default.yaml` is the template a new config is copied from and stays
    on the engine-wide default, because a template that silently spent an LLM call at ASSIGN would
    make the opt-in invisible to whoever copies it next.

    The count moved 12 -> 17 in D61 and the roster itself is pinned in `tests/test_styles.py`
    (`ENABLED_SEVENTEEN`), beside the registry the keys have to exist in — a length here and a
    roster there is the split that keeps this file from needing to know what a style is.
    """
    for name in ("hypedigitaly", "hypedigitaly-cs", "hypedigitaly-fresh"):
        cfg = load_config(name, configs_dir=CONFIGS_DIR)
        assert cfg.styles.assignment == "matched", f"{name} should pin D56's matched assignment"
        assert len(cfg.styles.enabled) == 17, \
            "the D61 17-key (D57's twelve + five teal-accented D61 styles) selection matched " \
            "mode guards"

    assert load_config("default", configs_dir=CONFIGS_DIR).styles.assignment == "rotation"


# --------------------------------------------------------------------------- the YAML 1.1 trap


def test_yaml11_off_as_a_boolean_is_given_back_to_a_text_enum(tmp_path: Path) -> None:
    """`notion_influence: off` is the PRD's own shipped spelling, but YAML 1.1 resolves the bare
    word to `False`. The enum offers "off", so the word is handed back (config.py `_unyaml_bool`)
    — otherwise the default config file would refuse to load."""
    cfg = load(tmp_path, "run:\n  notion_influence: off\n")
    assert cfg.run.notion_influence == "off"
    assert isinstance(cfg.run.notion_influence, str)

    # `no` is the same falsy trap and maps back to the same member.
    assert load(tmp_path, "run:\n  notion_influence: no\n").run.notion_influence == "off"

    # `on`/`yes` have no matching member here (`copy`/`full` are the truthy values), so the bare
    # word stays a bool and is refused by name — never guessed at.
    for spelling in ("on", "yes"):
        line = refusal(tmp_path, f"run:\n  notion_influence: {spelling}\n")
        assert "run.notion_influence" in line and "off | copy | full" in line


def test_yaml11_giveback_applies_to_notion_influence_too(tmp_path: Path) -> None:
    """`notion_influence: off` is a documented value of a text enum, same trap (W3.5 re-base:
    the pre-pivot example key left the schema; the YAML-1.1 giveback rule is what is tested)."""
    cfg = load(tmp_path, "run:\n  notion_influence: off\n")
    assert cfg.run.notion_influence == "off"


def test_yaml11_giveback_leaves_a_genuine_boolean_key_alone(tmp_path: Path) -> None:
    """"Applied only when the enum offers the matching word, so a genuine boolean key is
    untouched" — `craft_blocks: off` must stay the boolean False, not become the string "off"."""
    cfg = load(tmp_path, "run:\n  gauntlet:\n    craft_blocks: off\n"
                         "  carousel_anchor: no\n  reel_audio: on\n")

    assert cfg.run.gauntlet.craft_blocks is False
    assert cfg.run.carousel_anchor is False
    assert cfg.run.reel_audio is True


def test_yaml11_giveback_does_not_invent_a_member_the_enum_lacks(tmp_path: Path) -> None:
    """`reel_resolution: on` has no "on" member, so it stays a bool and is refused by name
    rather than being quietly coerced to a resolution the operator never wrote."""
    line = refusal(tmp_path, "run:\n  reel_resolution: on\n")
    assert "run.reel_resolution" in line and "480p | 720p" in line


# --------------------------------------------------------------------------- speed & picker


def test_nfr15_loading_the_shipped_default_stays_well_under_200ms() -> None:
    """NFR-15: "Config load and validation … SHALL complete in under 200ms so the menu appears
    near-instantly". Best of three, so one scheduler hiccup cannot fail the suite."""
    load_config("default")  # warm the type-hint cache before measuring
    best = min(_timed(lambda: load_config("default")) for _ in range(3))
    assert best < 0.200, f"config load took {best * 1000:.0f}ms"


def test_fr173_the_picker_describes_each_config_and_survives_a_broken_sibling(
    tmp_path: Path,
) -> None:
    """"Deliberately does not validate: one broken sibling must never blank the whole picker"."""
    write(tmp_path, "# A balanced default run\nrun: {}\n", "good.yaml")
    write(tmp_path, "niche:\n  audience: SME owners\n  vibe: blunt\n", "niched.yaml")
    write(tmp_path, "run:\n  formats: { image: 1\n", "broken.yaml")

    picker = {s.name: s.description for s in list_configs(tmp_path)}

    assert picker["good"] == "A balanced default run"
    assert picker["niched"] == "SME owners · blunt"
    assert picker["broken"] == ""  # listed, described as nothing, never raised


def test_fr173_an_author_written_label_wins_over_the_derived_niche_join(tmp_path: Path) -> None:
    """`label:` leads in `_describe` because a niche join is three sentences and two sibling niches
    can share a byte-identical `niche:` block — no truncation width can tell them apart, so naming
    itself is the file's job. The same file without the key keeps yesterday's behaviour exactly."""
    niche = "niche:\n  audience: SME owners\n  vibe: blunt\n"
    labelled = load(tmp_path, 'label: "the file names itself"\n' + niche)

    assert labelled.description == "the file names itself"
    assert labelled.label == "the file names itself"
    assert labelled.warnings == ()  # `label:` is a known key, not a typo to warn about

    derived = load(tmp_path, niche)
    assert derived.description == "SME owners · blunt"  # unchanged fallback
    assert derived.label == ""  # nothing was authored, so nothing is claimed


def test_fr173_a_blank_label_is_no_label_and_a_label_also_beats_the_line_one_comment(
    tmp_path: Path,
) -> None:
    """Three rungs, in order: `label:`, else the niche join, else line 1's comment. A whitespace-only
    label is not a self-description, so it must fall through rather than print an empty picker row."""
    blank = load(tmp_path, 'label: "   "\nniche:\n  audience: SME owners\n')
    assert blank.description == "SME owners"

    comment = load(tmp_path, "# a balanced default run\nrun: {}\n")
    assert comment.description == "a balanced default run"

    over_comment = load(tmp_path, '# a balanced default run\nlabel: "picked by the file"\n')
    assert over_comment.description == "picked by the file"


def test_fr173_the_picker_summary_separates_an_authored_label_from_a_derived_line(
    tmp_path: Path,
) -> None:
    """`list_configs` carries both, so the menu can tell an author's one-liner (already short
    enough) from a derived string it must truncate before printing."""
    write(tmp_path, 'label: "authored and short"\nniche:\n  audience: SME owners\n', "named.yaml")
    write(tmp_path, "niche:\n  audience: SME owners\n  vibe: blunt\n", "derived.yaml")

    rows = {s.name: s for s in list_configs(tmp_path)}

    assert (rows["named"].label, rows["named"].description) == ("authored and short",) * 2
    assert rows["derived"].label == ""
    assert rows["derived"].description == "SME owners · blunt"


def test_fr173_the_two_shipped_sibling_niches_resolve_distinct_picker_lines() -> None:
    """The reason the key exists: `hypedigitaly.yaml` and `hypedigitaly-cs.yaml` differ in exactly
    one behavioural line and used to describe themselves identically."""
    rows = {s.name: s.description for s in list_configs()}

    assert rows["hypedigitaly"] and rows["hypedigitaly-cs"]
    assert rows["hypedigitaly"] != rows["hypedigitaly-cs"]


def test_config_default_path_points_at_the_repo_configs_folder() -> None:
    """A `Config()` built in code (tests, previews) still resolves the shipped folder."""
    assert Config().path.parent == CONFIGS_DIR
    assert CONFIGS_DIR.name == "configs"


# --------------------------------------------------------------- the flags over this surface


def test_fr299_console_verbosity_is_a_sibling_of_log_verbosity_and_defaults_to_normal(
    tmp_path: Path,
) -> None:
    """FR-299 (contracts item 16): a NEW `output.console_verbosity` key beside `log_verbosity`.

    Two dials, deliberately separate. `log_verbosity` governs how much detail reaches
    events.jsonl; this one moves ONLY what reaches the screen — run.log and events.jsonl are
    unchanged by it. A single dial would have made a readable console cost the forensic record,
    which is the trade §1.10 exists to refuse.
    """
    default = load(tmp_path, "run: {}\n")
    assert (default.output.console_verbosity, default.output.log_verbosity) == ("normal", "normal")

    loud = load(tmp_path, "output:\n  console_verbosity: verbose\n")
    assert loud.output.console_verbosity == "verbose"
    assert loud.output.log_verbosity == "normal", "the console dial never moves the log dial"

    line = refusal(tmp_path, "output:\n  console_verbosity: loud\n")
    assert "output.console_verbosity" in line and "normal | verbose" in line


def test_fr299_the_verbose_flag_is_a_console_tier_and_never_a_config_override(
    tmp_path: Path,
) -> None:
    """`--verbose`/`-v` (FR-299) is the flag twin of the key above — but it applies NOTHING to the
    config. Verbosity is a console tier, not a config value: the runner reads `opts.verbose`
    beside `config.output.console_verbosity`, so `apply_overrides` has nothing to write and the
    run's override list stays a list of things that changed what the run DOES.
    """
    assert cli.parse_args([]).verbose is False
    assert cli.parse_args(["--verbose"]).verbose is True
    assert cli.parse_args(["-v"]).verbose is True  # the short form the operator will actually type

    cfg = load(tmp_path, "run: {}\n")
    applied = cli.apply_overrides(cfg, cli.parse_args(["-v"]))

    assert applied == []
    assert cfg.output.console_verbosity == "normal"  # untouched: the flag is read, not applied


def test_the_mode_flag_is_gone_with_ab_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """30 §5's `--mode` row is deleted (v2.0.0, operator decision #2): there is one render per
    creative, so there is no analyzed/direct/both to pick. argparse refuses it by name with exit
    2 — the same one-line boundary refusal every unknown flag gets (FR-63/69) — rather than
    accepting it and silently doing nothing, which is how a withdrawn flag rots."""
    with pytest.raises(SystemExit) as caught:
        cli.parse_args(["--mode", "both"])

    assert caught.value.code == 2
    assert "unrecognized arguments: --mode" in capsys.readouterr().err
    assert not hasattr(cli.parse_args([]), "mode")


def test_fr137_the_platforms_flag_refuses_the_same_typo_at_the_flag_boundary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--platforms` is the ONLY way to change the list (FR-137), so it enforces the same D6
    vocabulary as the file — argparse exits 2 with one line before any config is loaded
    (FR-63/69), which is what makes a typo cost $0 instead of a whole plan."""
    with pytest.raises(SystemExit) as caught:
        cli.parse_args(["--platforms", "linkedn,tiktok"])
    assert caught.value.code == 2
    assert "linkedin | instagram | tiktok" in capsys.readouterr().err

    opts = cli.parse_args(["--platforms", "tiktok, linkedin,tiktok"])
    assert opts.platforms == ["tiktok", "linkedin"]  # trimmed and deduped, like --sources

    config = Config()
    assert "run.platforms=tiktok,linkedin" in cli.apply_overrides(config, opts)
    assert config.run.platforms == ["tiktok", "linkedin"]


def test_fr314_the_styles_flag_overrides_the_files_selection_and_says_so(tmp_path: Path) -> None:
    """`--styles a,b` is the per-run twin of `styles.enabled` (FR-61: the file is never rewritten).

    Three things are the contract. It REPLACES rather than merges — a flag that unioned with the
    file could never narrow a niche config that had already narrowed. It records an override note,
    because the run header prints that list and a rotation restricted to two of eight styles is
    exactly the kind of change an operator must be able to see in `run.log` afterwards. And it is
    trimmed/deduped like `--platforms`, so a typed space is not a style key nobody defined.

    Deliberately NOT checked against the registry here: which keys exist depends on the
    `prompts_dir` seam (FR-174) and therefore on a config that is not loaded at parse time.
    `styles.validate` refuses an unknown key at pre-flight, exit 2, $0 — that is `test_styles.py`.
    """
    opts = cli.parse_args(["--styles", "beta, alpha,beta"])
    assert opts.styles == ["beta", "alpha"]

    cfg = load(tmp_path, "styles:\n  enabled: [gamma]\n")
    applied = cli.apply_overrides(cfg, opts)

    assert cfg.styles.enabled == ["beta", "alpha"], "replaced, never merged with the file's pick"
    assert "styles.enabled=beta,alpha" in applied

    # Without the flag the file's selection stands and nothing is claimed as an override.
    untouched = load(tmp_path, "styles:\n  enabled: [gamma]\n")
    assert cli.apply_overrides(untouched, cli.parse_args([])) == []
    assert untouched.styles.enabled == ["gamma"]


def test_fr314_an_empty_styles_flag_is_refused_rather_than_read_as_every_style(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--styles ""` means the opposite of what it looks like: an empty selection is "all styles",
    so accepting it would turn a deliberate narrowing into a silent widening. Refused at the flag
    boundary with exit 2, like every other malformed flag value (FR-63/69)."""
    with pytest.raises(SystemExit) as caught:
        cli.parse_args(["--styles", " , ,"])

    assert caught.value.code == 2
    assert "--styles" in capsys.readouterr().err
    assert cli.parse_args([]).styles is None  # not passed is not the same as an empty selection


def _timed(call) -> float:
    started = time.perf_counter()
    call()
    return time.perf_counter() - started


# ---------------------------------------- v2.2.0/D49: the `run.vision_check` migration


def test_d49_a_config_still_naming_vision_check_is_migrated_onto_the_gauntlet(
    tmp_path: Path,
) -> None:
    """The key is REMOVED, not deprecated — the FR-105 single-shot check it switched no longer
    exists in any form. Dropping it silently would do two wrong things at once: warn "unknown
    config key", and quietly turn a `vision_check: false` run into a GAUNTLETED one, which spends
    money the file explicitly said not to spend. So the boolean is carried across, once, with a
    sentence that says where it went.
    """
    cfg = load(tmp_path, "run:\n  vision_check: false\n")

    assert cfg.run.gauntlet.enabled is False, "the boolean means the same thing it meant"
    assert not hasattr(cfg.run, "vision_check"), "and the key itself is gone from the schema"
    assert any("run.vision_check is gone" in w and "run.gauntlet.enabled" in w
               for w in cfg.warnings)
    assert not any("unknown config key" in w for w in cfg.warnings), \
        "a migrated key is not a typo, and must not be reported as one"


def test_d49_an_explicit_gauntlet_block_wins_over_the_legacy_key(tmp_path: Path) -> None:
    """A file naming BOTH has already been migrated and the old key is a leftover, so the new key
    is authoritative — and the warning says so rather than silently preferring either one."""
    cfg = load(tmp_path, "run:\n  vision_check: false\n  gauntlet:\n    enabled: true\n")

    assert cfg.run.gauntlet.enabled is True
    assert any("delete the old key" in w for w in cfg.warnings)


# ------------------------------------------------ FR-333 / D54: the carousel copy-mode key + flag


def test_fr333_carousel_copy_mode_defaults_to_verbatim_and_parses_from_the_file(
    tmp_path: Path,
) -> None:
    """The engine-wide default is `verbatim` and it is a DEFAULT, not a fallback: a file that
    never mentions the key gets the pre-D54 behaviour byte for byte, because D50 ("reflow, never
    shorten") still governs verbatim mode and compress is an operator opt-in.

    Both spellings are real values of a text enum — there is no truthy/falsy word among them, so
    the YAML 1.1 trap that catches `notion_influence: off` cannot reach this key at all.
    """
    assert Config().run.carousel_copy_mode == "verbatim", "the dataclass default"
    assert load(tmp_path, "run: {}\n").run.carousel_copy_mode == "verbatim", "an absent key"

    for word in ("verbatim", "compress"):
        cfg = load(tmp_path, f"run:\n  carousel_copy_mode: {word}\n")
        assert cfg.run.carousel_copy_mode == word
        assert isinstance(cfg.run.carousel_copy_mode, str)


def test_fr333_a_bad_copy_mode_refuses_the_load_in_one_line_naming_both_words(
    tmp_path: Path,
) -> None:
    """A `Literal` enum validated at LOAD, exactly like `notion_influence` (FR-51/69): one
    operator-facing line, the key named, both accepted words printed, and the run never starts —
    so a typo costs exit 2 and $0 instead of a plan built on a mode nobody meant.

    `compressed` and `short` are the two typos this key invites; `true` is the third, because an
    operator reading "toggle" in the release note will try to switch it on like a boolean.
    """
    for spelling in ("compressed", "short", "true"):
        line = refusal(tmp_path, f"run:\n  carousel_copy_mode: {spelling}\n")
        assert "run.carousel_copy_mode" in line
        assert "verbatim | compress" in line, "the refusal has to name what IS accepted"


def test_fr333_the_copy_mode_flag_overrides_the_file_for_one_run_and_says_so(
    tmp_path: Path,
) -> None:
    """`--copy-mode` is the per-run twin of the key (FR-61: the flag wins, the file is never
    rewritten), and the applied-note matters — the run header prints that list, and switching a
    deck's whole copy contract from the command line is exactly the kind of change an operator
    has to be able to find in `run.log` afterwards.
    """
    cfg = load(tmp_path, "run:\n  carousel_copy_mode: verbatim\n")

    applied = cli.apply_overrides(cfg, cli.parse_args(["--copy-mode", "compress"]))

    assert cfg.run.carousel_copy_mode == "compress", "flag over file (FR-61)"
    assert "run.carousel_copy_mode=compress" in applied

    # It overrides in BOTH directions: a config that pinned compress can be walked back for one
    # run without editing the file, which is the shape of the W5 verification ladder.
    pinned = load(tmp_path, "run:\n  carousel_copy_mode: compress\n")
    assert "run.carousel_copy_mode=verbatim" in cli.apply_overrides(
        pinned, cli.parse_args(["--copy-mode", "verbatim"]))
    assert pinned.run.carousel_copy_mode == "verbatim"

    # And without the flag the file's value stands, claimed as no override at all.
    untouched = load(tmp_path, "run:\n  carousel_copy_mode: compress\n")
    assert cli.apply_overrides(untouched, cli.parse_args([])) == []
    assert untouched.run.carousel_copy_mode == "compress"
    assert cli.parse_args([]).copy_mode is None, "not passed is not the same as `verbatim`"


def test_fr333_the_copy_mode_flag_refuses_a_typo_at_the_flag_boundary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The same vocabulary enforced at the flag as in the file, and enforced BEFORE any config is
    loaded — argparse exits 2 with one line (FR-63/69), which is what makes a mistyped mode cost
    $0 rather than a whole plan."""
    with pytest.raises(SystemExit) as caught:
        cli.parse_args(["--copy-mode", "compressed"])

    assert caught.value.code == 2
    assert "--copy-mode" in capsys.readouterr().err


def test_fr353_the_three_brand_configs_ship_auto_and_the_engine_default_stays_verbatim() -> None:
    """D62's shipped posture, read off the files that actually ship.

    Three dated positions on one key, and this test states where they landed:

    - **D54** had the three brand configs opt IN to `compress`.
    - **D58** (2026-08-20) withdrew that pin: `compress` rewrites EVERY panel of a deck, including
      the ones that already fitted, and D56's text-dense archetypes plus FR-334 matched assignment
      had made most panels fit. Paying a model to rewrite a panel that fits, and losing the
      byte-substring claim on it, is a cost with no matching benefit.
    - **D62** (2026-08-21) pins `auto` instead. It answers the same defect D54 was written against
      — a 1,000-character panel on a frame whose style declares a 180-character slide budget — and
      answers it per PANEL: only the positions over that budget go to the model, everything else
      stays byte-verbatim, and a deck with nothing over budget makes no call at all. That is why it
      can be the shipped pin where `compress` could not.

    `configs/default.yaml` stays on `verbatim`, which is also the ENGINE default: a default that
    silently pays for LLM rewrites would re-price every config that never opted in, which is the
    same reasoning D58 used and the same reasoning `run.cover_candidates` ships 1 under.
    """
    for name in ("hypedigitaly", "hypedigitaly-cs", "hypedigitaly-fresh"):
        cfg = load_config(name, configs_dir=CONFIGS_DIR)
        assert cfg.run.carousel_copy_mode == "auto", f"{name} should ship D62's auto mode"
    assert load_config("default", configs_dir=CONFIGS_DIR).run.carousel_copy_mode == "verbatim", \
        "the engine default is what default.yaml documents; auto is a brand-config choice"


def test_fr333_d58_withdrew_a_pin_not_the_feature_compress_is_still_reachable(
    tmp_path: Path,
) -> None:
    """The half of D58 that a value assertion cannot state: compress still works.

    A withdrawn default that quietly became an unreachable code path would be a far worse
    regression than the pin ever was, and it would not show up in the test above. D62 did not
    change that either — `auto` took the shipped pin, it did not retire the mode it was built on.
    """
    shipped = load_config("hypedigitaly", configs_dir=CONFIGS_DIR)
    applied = cli.apply_overrides(shipped, cli.parse_args(["--copy-mode", "compress"]))

    assert shipped.run.carousel_copy_mode == "compress", "--copy-mode still turns compress on"
    assert "run.carousel_copy_mode=compress" in applied

    # And a config may still pin it directly — D58 changed three files, not the key's vocabulary.
    assert load(tmp_path, "run:\n  carousel_copy_mode: compress\n").run.carousel_copy_mode == (
        "compress")


def test_fr353_every_mode_is_reachable_from_the_file_and_from_the_flag(tmp_path: Path) -> None:
    """The key's vocabulary is three words wide, at both boundaries, and nothing else parses.

    `--copy-mode` and the config file are two doors onto one field, and D62 widened both: the flag
    takes `verbatim | auto | compress` through argparse's own `choices` (`cli._COPY_MODES`) and the
    file takes the same three through the `Literal` on `RunConfig`. A word neither door accepts is
    refused where it costs nothing — argparse exits at the boundary, the loader refuses at load,
    and neither ever guesses at a nearest match, because a misspelled mode is a different run than
    the one the operator asked for.
    """
    for mode in ("verbatim", "auto", "compress"):
        assert load(tmp_path, f"run:\n  carousel_copy_mode: {mode}\n").run.carousel_copy_mode == (
            mode)
        shipped = load_config("default", configs_dir=CONFIGS_DIR)
        cli.apply_overrides(shipped, cli.parse_args(["--copy-mode", mode]))
        assert shipped.run.carousel_copy_mode == mode

    assert cli._COPY_MODES == ("verbatim", "auto", "compress"), \
        "least to most lossy, engine default first — the order --help prints them in"
    with pytest.raises(SystemExit):  # argparse rejects at the boundary, before a run id exists
        cli.parse_args(["--copy-mode", "shorten"])
    with pytest.raises(ConfigError):
        load(tmp_path, "run:\n  carousel_copy_mode: shorten\n")


# ---- D62 ------------------------------------- FR-351: `run.cover_candidates` (the cover fan-out)


def test_fr351_cover_candidates_defaults_to_one_and_the_brand_configs_pin_three() -> None:
    """The shipped posture for the cover fan-out, and why the two halves differ.

    `1` is the ENGINE default and is the pre-D62 behaviour byte for byte: one slide-1 render, no
    pick call, no extra spend. The three brand configs pin `3`, because a carousel's cover is the
    one frame that decides whether the deck is opened at all and two more attempts at it are the
    cheapest quality buy in the run. The default stays at 1 for the D58 reason: a default that
    silently orders extra renders re-prices every config that never opted in.
    """
    for name in ("hypedigitaly", "hypedigitaly-cs", "hypedigitaly-fresh"):
        assert load_config(name, configs_dir=CONFIGS_DIR).run.cover_candidates == 3, name
    assert load_config("default", configs_dir=CONFIGS_DIR).run.cover_candidates == 1
    assert RunConfig().cover_candidates == 1, "the dataclass default, not only the shipped file"


def test_fr351_cover_candidates_is_bounded_one_to_three_and_says_so_when_refused(
    tmp_path: Path,
) -> None:
    """`_BOUNDS` is the ONE bound table and this key is in it, so the refusal is the house one-liner
    naming what IS accepted rather than "invalid value".

    The ceiling is a COST ceiling, not a taste: the pick reads every candidate in one vision call
    and the estimator prices N−1 extra covers per deck, so 4 is refused at load — before a run id
    exists and before a cent moves — rather than clamped into range. `2` is accepted because the
    range is real and not a two-value switch.
    """
    assert load(tmp_path, "run:\n  cover_candidates: 2\n").run.cover_candidates == 2

    for bad in ("0", "4"):
        with pytest.raises(ConfigError) as caught:
            load(tmp_path, f"run:\n  cover_candidates: {bad}\n")
        message = str(caught.value)
        assert "run.cover_candidates" in message
        assert "a whole number of cover candidates per carousel, 1–3" in message, message


# ---- D60 ----------------------------- FR-342: `platforms.<name>.image_resolution` (the 2K pin)
#
# One key with two readers, which is the whole reason it is worth this many tests. `budget.
# _image_price` turns it into the `models.price_per_unit.image.<tier>` line the operator approves
# at the Confirm gate, and every image render puts the same string into `RenderParams.resolution`.
# Both go through `Config.image_resolution()`, so the gate cannot quote one tier and the run buy
# another — CLAUDE.md rule 7 spelled out as a method. What is tested here is the LOADING half:
# what the file may say, what an absent key becomes, what a typo costs, and what the three shipped
# brand configs really pin. The spending half is in `tests/test_budget.py`, the wire-in in
# `tests/test_carousel.py`, `tests/test_generate_waves.py` and `tests/test_reel.py`.


def test_fr342_image_resolution_round_trips_on_a_platform_that_names_it(tmp_path: Path) -> None:
    """The plain case: a platform pins `2k` and both readers see `2k`.

    Asserted through the accessor as well as off the dataclass, because the accessor is the one
    every caller is required to use and a field that loaded correctly behind a broken accessor
    would still price and render at 1K.
    """
    cfg = load(tmp_path, "platforms:\n  linkedin:\n    image_resolution: 2k\n")

    assert cfg.platform("linkedin").image_resolution == "2k"
    assert cfg.image_resolution("linkedin") == "2k"


def test_fr342_an_omitted_key_defaults_to_1k_and_says_so_in_defaults_applied(
    tmp_path: Path,
) -> None:
    """FR-50's honesty line has to cover this key, and the D58 shape is why.

    The engine default is `1k` — a config that never asked for 2K keeps paying exactly what it
    paid before FR-342 existed, because a shipped pin that silently re-priced every run is the
    mistake D58 was the correction for. But "you are paying 1K because you never said" and "you
    are paying 1K because you wrote 1k" are different situations, and `defaults_applied` is the
    only place the run log tells them apart.

    The platform entry here is PRESENT and merely omits the key, which is the case that would slip
    through: a wholly absent `platforms.linkedin` block records the whole block instead, so a
    generic-path regression would still look fine from a test that never wrote the entry.
    """
    cfg = load(tmp_path, "platforms:\n  linkedin:\n    carousel_slides: 5\n")

    assert cfg.platform("linkedin").carousel_slides == 5, "the entry is present, not defaulted"
    assert cfg.image_resolution("linkedin") == "1k"
    assert "platforms.linkedin.image_resolution" in cfg.defaults_applied
    # And the other side of it: a file that DOES write the key is not reported as having defaulted.
    pinned = load(tmp_path, "platforms:\n  linkedin:\n    image_resolution: 2k\n")
    assert "platforms.linkedin.image_resolution" not in pinned.defaults_applied


def test_fr342_a_tier_outside_the_two_the_house_buys_is_one_line_at_load(tmp_path: Path) -> None:
    """FR-69's one-line refusal, on the key most likely to be typed hopefully.

    `4k` is the value an operator reaches for, and it is refused rather than clamped for a reason
    the Confirm gate owns: `render/profiles.py` folds a 4K request down to 2K (FR-192), so a config
    that accepted `4k` would let the estimator quote a price the renderer was never going to buy.
    A gate that quotes a number the run cannot spend is worse than no gate.

    The line names the KEY, the VALUE and the allowed set, because all three are what an operator
    needs to fix it without opening the schema — the same shape `notion_influence` and
    `run.reel_resolution` produce.
    """
    line = refusal(tmp_path, "platforms:\n  linkedin:\n    image_resolution: 4k\n")

    assert "platforms.linkedin.image_resolution" in line
    assert "'4k'" in line
    assert "one of: 1k | 2k" in line


def test_fr342_the_tier_is_case_sensitive_exactly_like_its_reel_resolution_sibling(
    tmp_path: Path,
) -> None:
    """`2K` is refused at load, and that is a documented match rather than an oversight.

    `_coerce` checks the `Literal` with no lower-casing, which is how `run.reel_resolution` has
    always behaved — `720P` gets the same refusal `2K` gets here. Keeping the two keys identical
    is worth more than being lenient on one of them: an operator who learns that resolutions are
    written lower-case learns it once, and a $0 refusal before a run id exists is the cheapest
    possible place to be told.

    The accessor's own lower-casing is the SEPARATE thing (next test) and does not contradict this:
    it exists for objects built in code, which never went through `_coerce` at all.
    """
    line = refusal(tmp_path, "platforms:\n  linkedin:\n    image_resolution: 2K\n")

    assert "platforms.linkedin.image_resolution" in line and "'2K'" in line
    assert "one of: 1k | 2k" in line
    # The sibling this matches, asserted beside it so the pairing is a decision and not a rumour.
    reel = refusal(tmp_path, "run:\n  reel_resolution: 720P\n")
    assert "run.reel_resolution" in reel and "'720P'" in reel


def test_fr342_the_accessor_lower_cases_and_falls_back_to_1k_for_an_unmentioned_platform(
    tmp_path: Path,
) -> None:
    """`Config.image_resolution()` is a READER, not a second validator, and the two halves of that
    are both load-bearing.

    The lower-casing is for objects that never met `_coerce` — the estimator's `SimpleNamespace`
    test doubles, a hand-built `Config`, an override applied in code. A caller comparing the answer
    to a literal `"2k"` must not have to think about it, and this is the only place that promise is
    checked, because a file can no longer deliver an upper-case value at all (test above).

    The `1k` fallback is FR-132's defaulting seen from this key: `platform()` invents an entry for a
    platform the file never mentioned, and what that entry must price and render at is exactly what
    `render/profiles.py` sends for an unset `RenderParams.resolution`, which is 1K. Anything else
    would make an unmentioned platform cost more than a mentioned one.
    """
    cfg = load(tmp_path, "platforms:\n  linkedin:\n    image_resolution: 2k\n")

    assert cfg.image_resolution("mastodon") == "1k", "FR-132: an unmentioned platform still reads"
    assert "mastodon" not in cfg.platforms, "…and reading it does not create it"

    cfg.platforms["linkedin"].image_resolution = "2K"  # type: ignore[assignment]
    assert cfg.image_resolution("linkedin") == "2k", "lower-cased for the caller, always"
    cfg.platforms["linkedin"].image_resolution = ""  # type: ignore[assignment]
    assert cfg.image_resolution("linkedin") == "1k", "empty means unset, and unset is 1K"


def test_fr342_the_three_shipped_brand_configs_pin_2k_on_the_three_platforms_they_publish_to(
) -> None:
    """The operator decision of 2026-08-20, pinned as data: 2K everywhere for colour accuracy.

    It is money, which is why it is asserted by NAME on all three configs rather than checked once.
    The pin costs $0.03 -> $0.05 per rendered slide and takes the critic's vision tokens from 1,398
    to 3,278 per frame — roughly +$3-6 on a nine-carousel run — so a config that silently lost the
    block would quietly halve the render quality the operator is paying for, and a config that
    silently gained a fourth platform would quietly raise the bill.

    `default` staying `1k` is the D58 shape and is the other half of the same decision: the pin
    lives in the three brand files that opted into it, never in the engine's own default, so a
    config that inherits `default.yaml` and nothing else keeps paying what it always paid. It is
    read through `load_config` rather than off the YAML so a key that loads to something other than
    what it looks like on disk is caught here.
    """
    for name in ("hypedigitaly", "hypedigitaly-cs", "hypedigitaly-fresh"):
        cfg = load_config(name, configs_dir=CONFIGS_DIR)

        for platform in ("linkedin", "instagram", "tiktok"):
            assert cfg.image_resolution(platform) == "2k", \
                f"{name}: {platform} lost D60's 2K pin — every slide silently re-prices to 1K"
        assert cfg.image_resolution("default") == "1k", \
            f"{name}: the 2K pin is per-platform and opt-in; `default` is not one of the three"

    assert load_config("default", configs_dir=CONFIGS_DIR).image_resolution("linkedin") == "1k", \
        "the ENGINE default never re-prices a config that did not opt in (D58 shape)"
