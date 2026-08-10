"""`hypesocials.config` — loading, defaulting and the one-line refusal (FR-50/51/69, NFR-15/19).

Every test drives the module's PUBLIC API only (`load_config`, `list_configs`, `Config`,
`ConfigError`); the private builders are exercised through it. All file I/O is in `tmp_path`,
except the two read-only assertions that the shipped `configs/*.yaml` still load.

The invariant behind most of these: a config file is *data*, so an absent key must default
(FR-50/NFR-19) and a malformed key must produce exactly ONE operator-facing line naming the key
and the expected shape (FR-51/69) — never a traceback, never a partial load.

The tail section covers a flag that overrides this same surface for one run (`--sources`,
FR-61/65/135): it lives here because what it changes — and never rewrites — is a config.
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
    cfg = load(tmp_path, "run:\n  spend_cap_usd: 3.5\n  vision_check: true\n")

    assert cfg.run.spend_cap_usd == 3.5
    assert cfg.run.vision_check is True
    # untouched keys — the defaults 30 §2 documents
    assert cfg.run.generation_mode == "analyzed"
    assert cfg.run.trend_history_days == 7
    assert cfg.run.run_deadline_min == 25
    assert cfg.sources.active == ["virlo"]
    assert cfg.models.analysis == "anthropic/claude-sonnet-5"
    assert cfg.output.dir == "output/"
    assert cfg.name == "unit" and cfg.path.name == "unit.yaml"


def test_fr50_defaults_applied_names_every_key_that_fell_back(tmp_path: Path) -> None:
    """"`defaults_applied` naming the keys that fell back" — the run log's honesty line."""
    cfg = load(tmp_path, "run:\n  spend_cap_usd: 3.5\n")

    assert "run.vision_check" in cfg.defaults_applied
    assert "sources" in cfg.defaults_applied  # the whole block was absent
    assert "run.spend_cap_usd" not in cfg.defaults_applied
    assert cfg.warnings == ()


def test_nfr19_an_empty_file_loads_as_a_full_default_config(tmp_path: Path) -> None:
    """NFR-19: "any file predating the new key continues to load successfully using that key's
    documented default" — the limit case is a file that predates every key."""
    cfg = load(tmp_path, "# nothing but a comment\n")

    assert cfg.run.formats == {"image": 4, "carousel": 2, "reel": 0}
    assert cfg.run.text_budgets.image_headline == 42
    assert cfg.platforms  # per-platform defaults are built even with no platforms: block
    assert cfg.description == "nothing but a comment"  # FR-173 picker line


def test_nfr19_a_partial_mapping_merges_key_by_key_instead_of_replacing_it(
    tmp_path: Path,
) -> None:
    """30 §1: "a variant lists only what it overrides". Naming one format must not delete the
    other two, or a niche file would silently zero the run."""
    cfg = load(tmp_path, "run:\n  formats: { image: 1 }\n  text_budgets:\n    image_headline: 30\n")

    assert cfg.run.formats == {"image": 1, "carousel": 2, "reel": 0}
    assert cfg.run.text_budgets.image_headline == 30
    assert cfg.run.text_budgets.image_subline == 60  # untouched sibling keeps its default
    assert "run.text_budgets.image_subline" in cfg.defaults_applied


def test_fr132_platform_defaults_are_per_platform_not_shared(tmp_path: Path) -> None:
    """30 §2: image + carousel everywhere, reel allowlisted on TikTok only, 5 slides."""
    cfg = load(tmp_path, "run:\n  platforms: [linkedin, tiktok]\n")

    assert cfg.platform("linkedin").formats == ["image", "carousel"]
    assert cfg.platform("tiktok").formats == ["image", "carousel", "reel"]
    assert cfg.platform("linkedin").carousel_slides == 5
    assert cfg.platform("mastodon").formats == ["image", "carousel"]  # unnamed platform defaults


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
    line = refusal(tmp_path, "run:\n  vision_check: maybe\n")
    assert "run.vision_check" in line and "expected true or false" in line


def test_fr69_a_value_outside_a_closed_vocabulary_lists_the_options(tmp_path: Path) -> None:
    line = refusal(tmp_path, "run:\n  generation_mode: creative\n")
    assert "run.generation_mode" in line
    assert "analyzed | direct | both" in line


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
    cfg = load(tmp_path, "run:\n  spend_cap_usd: 2\n  vision_chek: true\nnonsense: 1\n")

    assert any("run.vision_chek" in w for w in cfg.warnings)
    assert any("nonsense" in w for w in cfg.warnings)
    assert cfg.run.vision_check is False  # the real key kept its default


def test_nfr111_a_token_cap_under_its_floor_is_clamped_up_with_a_warning(tmp_path: Path) -> None:
    """NFR-111: below the floor a cap buys truncation retries instead of saving money."""
    cfg = load(tmp_path, "models:\n  max_tokens: { analysis: 50 }\n")

    assert cfg.max_tokens_for("analysis") == cfg.models.max_tokens_floor["analysis"]
    assert any("max_tokens.analysis" in w and "clamped" in w for w in cfg.warnings)

    line = refusal(
        tmp_path,
        "models:\n  max_tokens: { analysis: 0 }\n  max_tokens_floor: { analysis: 0 }\n")
    assert "max_tokens_floor.analysis" in line


def test_fr131_reels_requested_without_a_price_warn_rather_than_fail_the_load(
    tmp_path: Path,
) -> None:
    """10 §10: "Reels are not planned at all; the menu reports the missing price" — the config
    still loads, because the drop happens at pre-flight, not here."""
    cfg = load(tmp_path, "run:\n  formats: { reel: 2 }\n")

    assert cfg.reels_plannable is False
    assert cfg.reel_price_key == "models.price_per_unit.reel_second.720p"
    assert any("reel_second" in w for w in cfg.warnings)

    priced = load(tmp_path, "run:\n  formats: { reel: 2 }\n"
                            "models:\n  price_per_unit:\n    reel_second: { '720p': 0.19 }\n")
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
    warned = load(tmp_path, priced)  # deadline defaults to 25 min = 1500 s < 1800 s
    assert any("run_deadline_min" in w and "video_job_timeout_s" in w for w in warned.warnings)

    quiet = load(tmp_path, "run:\n  run_deadline_min: 45\n" + priced)
    assert not any("run_deadline_min" in w for w in quiet.warnings)
    # Reels unreachable (default.yaml's shape): the same 25/1800 pairing is silent.
    assert not any("run_deadline_min" in w for w in load(tmp_path, "run: {}\n").warnings)


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


def test_yaml11_giveback_applies_to_inspiration_mix_too(tmp_path: Path) -> None:
    """`inspiration_mix: off` is a documented value of a text enum (D13), same trap."""
    cfg = load(tmp_path, "sources:\n  inspiration_mix: off\n")
    assert cfg.sources.inspiration_mix == "off"


def test_yaml11_giveback_leaves_a_genuine_boolean_key_alone(tmp_path: Path) -> None:
    """"Applied only when the enum offers the matching word, so a genuine boolean key is
    untouched" — `vision_check: off` must stay the boolean False, not become the string "off"."""
    cfg = load(tmp_path, "run:\n  vision_check: off\n  carousel_anchor: no\n  reel_audio: on\n")

    assert cfg.run.vision_check is False
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


def test_config_default_path_points_at_the_repo_configs_folder() -> None:
    """A `Config()` built in code (tests, previews) still resolves the shipped folder."""
    assert Config().path.parent == CONFIGS_DIR
    assert CONFIGS_DIR.name == "configs"


# --------------------------------------------------------------------------- the --sources flag


def test_fr65_the_sources_flag_overrides_sources_active_without_rewriting_the_file(
    tmp_path: Path,
) -> None:
    """30 §5: the CLI twin of the menu's source picker — flags win for this run only (FR-61)."""
    path = write(tmp_path, "sources:\n  active: [google_trends]\n")
    cfg = load_config("unit", configs_dir=tmp_path)

    assert cli.parse_args([]).sources == ()  # no flag, no override: the file's list stands
    applied = cli.apply_overrides(cfg, cli.parse_args(["--sources", "virlo, virlo"]))

    assert cfg.sources.active == ["virlo"]  # deduped, exactly as the picker dedupes its pick
    assert "sources.active=virlo" in applied
    assert "google_trends" in path.read_text(encoding="utf-8")


def test_fr135_the_sources_flag_refuses_an_unknown_and_an_unbuilt_adapter_in_one_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FR-63/69: one line, exit 2, before any config load — and never a silent no-op (FR-135)."""
    for value, expected in (("reddit", "expected a comma-separated list of"),
                            ("virlo,google_trends", "not built yet")):
        with pytest.raises(SystemExit) as caught:
            cli.parse_args(["--sources", value])
        assert caught.value.code == 2
        assert expected in capsys.readouterr().err


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


def _timed(call) -> float:
    started = time.perf_counter()
    call()
    return time.perf_counter() - started
