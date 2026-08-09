"""The logging boundary: redaction and the run.log / events.jsonl split (FR-77–81, 152, NFR-23).

D30's guarantee is that a secret is never interpolated into a prompt in the first place; the
`LogWriter` is the **backstop** — so these tests deliberately push API-key-shaped strings through
every channel the writer accepts (message, nested payload, list, prompt body, header dict, bytes)
and assert the key reaches neither file.

The second half asserts 40 §4's split: full prompts and payloads live in `events.jsonl` only,
`run.log` gets a one-line digest naming the size. Everything runs in `tmp_path`; no network.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hypesocials.outputs import LogWriter

#: Realistically shaped credentials — long, distinctive, and the exact thing D30 forbids logging.
KIE_KEY = "kie-live-9f3b7a21c4d8e6f05b2a7c19d4e8f6a3"
OPENROUTER_KEY = "sk-or-v1-7c1d9e4b8a2f6035d7e1c9b4a8f2036d5e7c1b9a"
VIRLO_KEY = "virlo_pk_82ac91d7"
SECRETS = (KIE_KEY, OPENROUTER_KEY, VIRLO_KEY)

ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")


# --------------------------------------------------------------------------- helpers


@pytest.fixture
def writer(tmp_path: Path):
    """One `LogWriter` over a temp run folder, holding the three real secret shapes."""
    log = LogWriter(tmp_path, SECRETS)
    yield log
    log.close()


def run_log(tmp_path: Path) -> str:
    return (tmp_path / "run.log").read_text(encoding="utf-8")


def events_text(tmp_path: Path) -> str:
    return (tmp_path / "events.jsonl").read_text(encoding="utf-8")


def events(tmp_path: Path) -> list[dict]:
    return [json.loads(line) for line in events_text(tmp_path).splitlines() if line.strip()]


def assert_no_secret(tmp_path: Path) -> None:
    """The single assertion this whole file exists for."""
    for blob in (run_log(tmp_path), events_text(tmp_path)):
        for secret in SECRETS:
            assert secret not in blob


# --------------------------------------------------------------------------- FR-152 redaction


def test_fr152_a_secret_in_the_message_never_reaches_either_file(
    writer: LogWriter, tmp_path: Path
) -> None:
    """FR-152: "any value matching a configured secret is replaced with `[REDACTED]`"."""
    writer.event("http_call", f"POST https://api.kie.ai/createTask key={KIE_KEY}")

    assert_no_secret(tmp_path)
    assert "[REDACTED]" in run_log(tmp_path)
    assert events(tmp_path)[0]["message"].endswith("key=[REDACTED]")
    assert "https://api.kie.ai/createTask" in run_log(tmp_path)  # only the secret is masked


def test_fr152_a_secret_is_masked_at_any_payload_depth(
    writer: LogWriter, tmp_path: Path
) -> None:
    """"…wherever it appears — in the message, at any payload depth". A dashboard parses
    events.jsonl, so a secret buried three levels down is a leak with a longer fuse."""
    writer.event(
        "render_submit",
        "submitting",
        detail={"provider": {"base_url": f"https://kie.ai?token={KIE_KEY}",
                             "retries": [{"attempt": 1, "sent": OPENROUTER_KEY}]}},
        candidates=[VIRLO_KEY, "harmless"],
    )

    assert_no_secret(tmp_path)
    record = events(tmp_path)[0]["data"]
    assert record["detail"]["provider"]["base_url"] == "https://kie.ai?token=[REDACTED]"
    assert record["detail"]["provider"]["retries"][0]["sent"] == "[REDACTED]"
    assert record["candidates"] == ["[REDACTED]", "harmless"]


def test_fr152_credential_named_keys_are_masked_whatever_their_value(
    writer: LogWriter, tmp_path: Path
) -> None:
    """"auth headers are stripped from logged request/response payloads before writing" — the
    key NAME is enough; a header value the run never configured as a secret is masked too."""
    writer.event("http_call", "GET /trends", headers={
        "Authorization": "Bearer never-configured-anywhere",
        "X-API-Key": "also-not-in-the-secret-set",
        "Cookie": "session=abc",
        "client_secret": "shhh",
        "Content-Type": "application/json",
    })

    headers = events(tmp_path)[0]["data"]["headers"]
    assert headers["Authorization"] == "[REDACTED]"
    assert headers["X-API-Key"] == "[REDACTED]"
    assert headers["Cookie"] == "[REDACTED]"
    assert headers["client_secret"] == "[REDACTED]"
    assert headers["Content-Type"] == "application/json"  # not credential material
    assert "never-configured-anywhere" not in events_text(tmp_path)
    assert "never-configured-anywhere" not in run_log(tmp_path)


def test_fr152_the_ledger_audit_trail_stays_readable(
    writer: LogWriter, tmp_path: Path
) -> None:
    """FR-203's ids are the whole point of the ledger; masking them would redact the audit trail
    instead of the credentials. `request_token` / `task_id` deliberately do not match."""
    writer.event("ledger", "submitted", request_token="req-0001", task_id="kie_xyz789",
                 asset_id="Li_img_dance_analyzed_01")

    data = events(tmp_path)[0]["data"]
    assert data == {"request_token": "req-0001", "task_id": "kie_xyz789",
                    "asset_id": "Li_img_dance_analyzed_01"}
    assert "kie_xyz789" in run_log(tmp_path)


def test_fr152_short_values_are_not_treated_as_secrets(tmp_path: Path) -> None:
    """A 3-character "secret" would redact ordinary words out of the narrative — the log has to
    stay the explanation, so the writer ignores anything under six characters."""
    with LogWriter(tmp_path, ("abc", "on", "")) as log:
        log.event("plan", "abc is a normal word on a line")

    assert "abc is a normal word on a line" in run_log(tmp_path)
    assert "[REDACTED]" not in run_log(tmp_path)


def test_fr152_overlapping_secrets_are_masked_whole(tmp_path: Path) -> None:
    """"Longest first, so a key that contains another key is masked whole" — otherwise the
    shorter match leaves the tail of the longer key sitting in the log."""
    short, long = "prefix-secret", "prefix-secret-with-suffix"
    with LogWriter(tmp_path, (short, long)) as log:
        log.event("http_call", f"sent {long} and {short}")

    line = run_log(tmp_path)
    assert long not in line and short not in line
    assert line.count("[REDACTED]") == 2


def test_fr152_binary_payloads_become_a_size_note_not_content(
    writer: LogWriter, tmp_path: Path
) -> None:
    """Vision calls carry image bytes (FR-40); base64 in a log is neither readable nor safe."""
    writer.event("vision_call", "analysing", images=[b"\x89PNG" + b"\x00" * 4096])

    assert events(tmp_path)[0]["data"]["images"] == ["<4100 bytes>"]
    assert "PNG" not in events_text(tmp_path)


def test_fr152_the_narrative_blocks_are_redacted_too(
    writer: LogWriter, tmp_path: Path
) -> None:
    """`narrative()` writes the launch summary and the FR-84 spend table — the same text the
    console prints, so an unredacted block would leak to the screen as well as to disk."""
    printed = writer.narrative(f"launch summary\n  virlo key: {VIRLO_KEY}\n  cap: $10.00")

    assert VIRLO_KEY not in printed and "[REDACTED]" in printed
    assert_no_secret(tmp_path)
    assert "cap: $10.00" in run_log(tmp_path)


def test_d30_a_secret_smuggled_inside_a_prompt_is_still_caught(
    writer: LogWriter, tmp_path: Path
) -> None:
    """D30: "redaction here is the backstop, not the defense". Prompts are logged IN FULL to
    events.jsonl (FR-80), so the backstop has to hold precisely there."""
    writer.event("render_prompt", "assembled", prompt=f"Render this. (debug key {KIE_KEY})")

    assert_no_secret(tmp_path)
    assert "[REDACTED]" in events(tmp_path)[0]["data"]["prompt"]


def test_fr152_the_secret_set_itself_is_never_written(
    writer: LogWriter, tmp_path: Path
) -> None:
    """The writer holds the values; nothing it writes may enumerate them."""
    writer.event("launch", "run started", config="hypedigitaly.yaml")
    writer.warn("degraded", "notion unavailable")

    assert_no_secret(tmp_path)
    assert "secret" not in run_log(tmp_path).lower()


# --------------------------------------------------------------------------- the 40 §4 split


def test_fr80_full_prompts_go_to_events_jsonl_and_run_log_gets_a_size_digest(
    writer: LogWriter, tmp_path: Path
) -> None:
    """40 §4: "Full prompts and full payloads are ALWAYS written to `events.jsonl`; `run.log`
    carries one-line digests"."""
    prompt = "Reproduce this exact template. " * 60
    writer.event("creative_submitted", "Li_img_dance_analyzed_01", prompt=prompt,
                 messages=[{"role": "user", "content": prompt}], kie_job_id="kie_1")

    log_text = run_log(tmp_path)
    assert prompt not in log_text
    assert f"prompt=<{len(prompt)} chars in events.jsonl>" in log_text
    assert "messages=<" in log_text and "in events.jsonl>" in log_text
    assert "kie_job_id=kie_1" in log_text  # small fields stay inline and readable

    assert events(tmp_path)[0]["data"]["prompt"] == prompt


def test_fr81_both_files_receive_every_event_and_stay_in_sync(
    writer: LogWriter, tmp_path: Path
) -> None:
    """FR-81: "Both run.log and events.jsonl are written concurrently as each event fires; they
    are always in sync"."""
    for index in range(5):
        writer.event("job_polled", f"poll {index}", attempt=index)

    assert len(events(tmp_path)) == 5
    assert len([line for line in run_log(tmp_path).splitlines() if line.strip()]) == 5


def test_fr81_every_events_line_is_one_whole_json_object(
    writer: LogWriter, tmp_path: Path
) -> None:
    """"a torn JSONL line breaks every downstream parser of events.jsonl". Multi-line values
    must not become multi-line records."""
    writer.event("copy_written", "a caption", caption="line1\nline2\nline3")

    lines = [line for line in events_text(tmp_path).splitlines() if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["data"]["caption"] == "line1\nline2\nline3"
    # the run.log digest flattens the multi-line VALUE so the digest stays one line
    assert len(run_log(tmp_path).splitlines()) == 1
    assert "caption=line1 line2 line3" in run_log(tmp_path)


@pytest.mark.xfail(
    strict=True,
    reason="DEFECT (logwriter.py:186 `_digest`): data VALUES are newline-flattened but the "
           "message is not, so a multi-line `message=` splits one event across several run.log "
           "lines, against 40 §4's 'run.log carries one-line digests'. Reported, not fixed "
           "(T5.5 owns tests only). Remove this marker when the digest clips the message.",
)
def test_40s4_a_multiline_message_should_still_be_one_run_log_line(
    writer: LogWriter, tmp_path: Path
) -> None:
    """40 §4: `run.log` carries "one-line digests"; `narrative()` is the sanctioned multi-line
    path. A provider error or a caption passed as `message` currently tears the digest."""
    writer.event("render_failed", "provider said:\nContent policy\nrefused")

    assert len(run_log(tmp_path).splitlines()) == 1


def test_fr78_timestamps_are_iso_8601_and_durations_are_milliseconds(
    writer: LogWriter, tmp_path: Path
) -> None:
    """FR-78: "Timestamps use ISO 8601 format …; durations are in milliseconds (e.g. `342ms`)"."""
    writer.event("kie_call", "createTask", duration_ms=342)

    record = events(tmp_path)[0]
    assert ISO.fullmatch(record["timestamp"])
    assert record["duration_ms"] == 342
    assert "(342ms)" in run_log(tmp_path)
    assert ISO.search(run_log(tmp_path))


def test_fr73_the_returned_event_id_is_the_pointer_meta_yaml_stores(
    writer: LogWriter, tmp_path: Path
) -> None:
    """FR-73's `event_id` ("ev_20260808_1234") is how an asset folder points back into the log."""
    first = writer.event("a", "one")
    second = writer.event("b", "two")

    assert re.fullmatch(r"ev_\d{8}_\d{4}", first)
    assert first != second
    assert [record["event_id"] for record in events(tmp_path)] == [first, second]


def test_levels_are_carried_on_both_files(writer: LogWriter, tmp_path: Path) -> None:
    """§11's taxonomy: a warning is a survived degradation, an error cost the operator something."""
    writer.warn("trend_history_locked", "continuing read-only")
    writer.error("render_failed", "kie_timeout")

    assert [record["level"] for record in events(tmp_path)] == ["warn", "error"]
    assert "WARN " in run_log(tmp_path) and "ERROR" in run_log(tmp_path)


def test_verbose_only_events_stay_out_of_a_normal_run_log_but_never_out_of_events(
    tmp_path: Path,
) -> None:
    """40 §4: verbosity is `normal|verbose` and governs run.log only — "events.jsonl always gets
    the event, because it is the machine record"."""
    normal_dir, verbose_dir = tmp_path / "normal", tmp_path / "verbose"
    with LogWriter(normal_dir, SECRETS) as quiet:
        quiet.event("poll_detail", "T0+2s pending", verbose_only=True)
        quiet.event("creative_submitted", "Li_img_dance_analyzed_01")
    with LogWriter(verbose_dir, SECRETS, verbose=True) as loud:
        loud.event("poll_detail", "T0+2s pending", verbose_only=True)
        loud.event("creative_submitted", "Li_img_dance_analyzed_01")

    assert "poll_detail" not in run_log(normal_dir)
    assert len(events(normal_dir)) == 2
    assert "poll_detail" in run_log(verbose_dir)
    assert len(events(verbose_dir)) == 2


# --------------------------------------------------------------------------- NFR-23 durability


def test_nfr23_every_event_is_flushed_so_an_interrupted_run_has_a_truthful_tail(
    writer: LogWriter, tmp_path: Path
) -> None:
    """NFR-23: "flushed to disk after every event … if the run is interrupted, the log tail is
    always truthful". Read through separate handles with the writer still open — a killed process
    never gets to call `close()`."""
    writer.event("virlo_fetch_complete", "27 trends found")
    assert "27 trends found" in run_log(tmp_path)
    assert len(events(tmp_path)) == 1

    writer.event("creative_submitted", "Li_img_dance_analyzed_01")
    assert len(events(tmp_path)) == 2
    assert events(tmp_path)[-1]["event_type"] == "creative_submitted"


def test_close_is_idempotent_because_every_exit_path_calls_it(tmp_path: Path) -> None:
    """The runner closes the writer in a `finally` that itself may run twice on a hard Ctrl+C."""
    log = LogWriter(tmp_path, SECRETS)
    log.event("launch", "started")
    log.close()
    log.close()

    assert "started" in run_log(tmp_path)


def test_a_second_writer_appends_rather_than_truncating_the_run_log(tmp_path: Path) -> None:
    """Both files are opened in append mode: a log is evidence, and evidence is not overwritten."""
    with LogWriter(tmp_path, SECRETS) as first:
        first.event("launch", "first line")
    with LogWriter(tmp_path, SECRETS) as second:
        second.event("resume", "second line")

    assert "first line" in run_log(tmp_path) and "second line" in run_log(tmp_path)
    assert len(events(tmp_path)) == 2


def test_the_log_files_are_utf8_with_lf_newlines(tmp_path: Path) -> None:
    """FR-256: Czech diacritics and hook text survive the round trip, and no CRLF translation
    can tear a JSONL line on Windows."""
    with LogWriter(tmp_path, SECRETS) as log:
        log.event("copy_written", "hook: Příliš žluťoučký kůň", headline="Ještě větší dosah")

    blob = (tmp_path / "events.jsonl").read_bytes()
    assert b"\r\n" not in blob
    assert "Příliš žluťoučký kůň" in blob.decode("utf-8")
    assert b"\r\n" not in (tmp_path / "run.log").read_bytes()
