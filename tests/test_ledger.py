"""`LEDGER.txt` — the append-only record of what the run already bought (FR-203, 40 §10).

The ledger exists for endings the run did not plan for: a Ctrl+C, a deadline, a lost response.
Its two load-bearing properties are therefore *when* a line lands (intent BEFORE `createTask`)
and that nothing is ever edited (append-only, last line for a taskId wins). Both are asserted
here on the real file, in `tmp_path`; nothing is mocked and nothing is submitted.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from hypesocials.outputs import Ledger
from hypesocials.outputs.state import LEDGER_FILE

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# --------------------------------------------------------------------------- helpers


def rows(run_dir: Path) -> list[list[str]]:
    """Every ledger line split into its CSV fields, in file order."""
    text = (run_dir / LEDGER_FILE).read_text(encoding="utf-8")
    return [line.split(",") for line in text.splitlines() if line]


def raw(run_dir: Path) -> str:
    return (run_dir / LEDGER_FILE).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- entry shape


def test_fr203_the_ledger_lives_in_the_run_folder_and_is_created_on_first_write(
    tmp_path: Path,
) -> None:
    """40 §10: "a file at `output/<run_id>/LEDGER.txt`". A run that submitted nothing leaves no
    ledger — the folder is made, the file is not invented."""
    run_dir = tmp_path / "20260808_143022_x7q2"
    ledger = Ledger(run_dir)

    assert ledger.path == run_dir / "LEDGER.txt"
    assert run_dir.is_dir()
    assert not ledger.path.exists()

    ledger.intent("Li_img_dance_analyzed_01", "req-0001")
    assert ledger.path.is_file()


def test_fr203_intent_line_is_written_before_the_call_with_no_task_id_yet(
    tmp_path: Path,
) -> None:
    """FR-203's intent-before-call pattern: "a line carrying the creative id and a
    client-generated request token is appended **before** the `createTask` call goes out"."""
    ledger = Ledger(tmp_path)
    ledger.intent("Li_img_dance_analyzed_01", "req-0001")

    (stamp, asset_id, token, task_id, status), = rows(tmp_path)
    assert ISO.fullmatch(stamp)  # FR-78
    assert asset_id == "Li_img_dance_analyzed_01"
    assert token == "req-0001"
    assert task_id == ""  # nothing has been accepted yet — there IS no task id
    assert status == "intent"


def test_fr203_submitted_line_carries_the_task_id_the_response_returned(
    tmp_path: Path,
) -> None:
    """"the `taskId` is appended once the response arrives"."""
    ledger = Ledger(tmp_path)
    ledger.intent("Li_img_dance_analyzed_01", "req-0001")
    ledger.submitted("Li_img_dance_analyzed_01", "req-0001", "kie_xyz789")

    assert [row[3:] for row in rows(tmp_path)] == [["", "intent"], ["kie_xyz789", "submitted"]]


def test_fr203_a_lost_response_is_recorded_as_submit_unknown_not_as_nothing(
    tmp_path: Path,
) -> None:
    """"A submission whose response is lost … therefore still has a ledger line, marked
    `submit_unknown`, instead of being invisible — which is the exact case the ledger exists
    for." Billed work with no taskId in hand is still billed work."""
    ledger = Ledger(tmp_path)
    ledger.intent("Tk_reel_dance_direct_03", "req-0003")
    ledger.submitted("Tk_reel_dance_direct_03", "req-0003", None)

    last = rows(tmp_path)[-1]
    assert last[3] == "" and last[4] == "submit_unknown"
    assert last[1:3] == ["Tk_reel_dance_direct_03", "req-0003"]


def test_fr203_terminal_statuses_cover_the_endings_the_run_did_not_plan(
    tmp_path: Path,
) -> None:
    """FR-108/FR-201: "the ledger records which tasks were left **in flight**". `abandoned` is
    the deadline/interrupt ending and it is a terminal line like any other."""
    ledger = Ledger(tmp_path)
    for index, status in enumerate(("success", "fail", "stuck", "abandoned")):
        asset_id = f"Li_img_dance_analyzed_{index + 1:02d}"
        ledger.intent(asset_id, f"req-{index}")
        ledger.submitted(asset_id, f"req-{index}", f"kie_{index}")
        ledger.terminal(asset_id, f"req-{index}", f"kie_{index}", status)

    statuses = [row[4] for row in rows(tmp_path)]
    assert statuses == ["intent", "submitted", "success",
                        "intent", "submitted", "fail",
                        "intent", "submitted", "stuck",
                        "intent", "submitted", "abandoned"]


def test_fr203_every_line_has_the_same_five_fields(tmp_path: Path) -> None:
    """A ledger a human greps and a script parses: one shape, always."""
    ledger = Ledger(tmp_path)
    ledger.intent("a", "t")
    ledger.submitted("a", "t", "kie_1")
    ledger.submitted("b", "u", None)
    ledger.terminal("a", "t", "kie_1", "success")

    assert {len(row) for row in rows(tmp_path)} == {5}
    assert all(ISO.fullmatch(row[0]) for row in rows(tmp_path))


# --------------------------------------------------------------------------- append-only


def test_fr203_the_file_is_append_only_and_earlier_bytes_never_change(
    tmp_path: Path,
) -> None:
    """40 §10: "append-only … the last line for a taskId wins (no in-place updates — an appended
    CSV cannot be edited without a rewrite)". A rewrite is exactly what a kill mid-run must not
    be able to corrupt."""
    ledger = Ledger(tmp_path)
    ledger.intent("Li_img_dance_analyzed_01", "req-0001")
    after_intent = raw(tmp_path)

    ledger.submitted("Li_img_dance_analyzed_01", "req-0001", "kie_xyz789")
    after_submit = raw(tmp_path)

    ledger.terminal("Li_img_dance_analyzed_01", "req-0001", "kie_xyz789", "success")
    final = raw(tmp_path)

    assert after_submit.startswith(after_intent)  # nothing before was touched
    assert final.startswith(after_submit)
    assert len(rows(tmp_path)) == 3


def test_fr203_the_last_line_for_a_task_id_wins(tmp_path: Path) -> None:
    """The reader's rule, stated as a reader would apply it: group by task id, take the last."""
    ledger = Ledger(tmp_path)
    ledger.intent("Li_img_dance_analyzed_01", "req-1")
    ledger.submitted("Li_img_dance_analyzed_01", "req-1", "kie_1")
    ledger.terminal("Li_img_dance_analyzed_01", "req-1", "kie_1", "abandoned")
    ledger.terminal("Li_img_dance_analyzed_01", "req-1", "kie_1", "success")  # late grace poll

    latest: dict[str, str] = {}
    for row in rows(tmp_path):
        if row[3]:
            latest[row[3]] = row[4]
    assert latest == {"kie_1": "success"}


def test_fr203_a_second_ledger_object_for_the_same_run_appends_rather_than_truncates(
    tmp_path: Path,
) -> None:
    """Nothing in the ledger's contract says one object per run; opening it again must never be
    the thing that erases what was already bought."""
    Ledger(tmp_path).intent("a", "t1")
    Ledger(tmp_path).intent("b", "t2")

    assert [row[1] for row in rows(tmp_path)] == ["a", "b"]


def test_fr203_lines_stay_chronological_across_interleaved_creatives(tmp_path: Path) -> None:
    """The ledger is a timeline of a concurrent batch (D5), so order is arrival order."""
    ledger = Ledger(tmp_path)
    ledger.intent("a", "t1")
    ledger.intent("b", "t2")
    ledger.submitted("b", "t2", "kie_b")
    ledger.submitted("a", "t1", "kie_a")

    assert [(row[1], row[4]) for row in rows(tmp_path)] == [
        ("a", "intent"), ("b", "intent"), ("b", "submitted"), ("a", "submitted")]

    stamps = [datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%S.%fZ") for row in rows(tmp_path)]
    assert stamps == sorted(stamps)


# --------------------------------------------------------------------------- robustness


def test_fr203_a_field_carrying_a_comma_or_newline_cannot_tear_the_line(
    tmp_path: Path,
) -> None:
    """One append, one line — a CSV a downstream `split(",")` can trust. The separator is
    neutralized in the value, never escaped into a second field."""
    ledger = Ledger(tmp_path)
    ledger.terminal("Li_img_x_analyzed_01", "req,with,commas", "kie_1\nkie_2",
                    "fail: timeout, then dropped")

    lines = raw(tmp_path).splitlines()
    assert len(lines) == 1
    fields = lines[0].split(",")
    assert len(fields) == 5
    assert fields[2] == "req;with;commas"
    assert fields[3] == "kie_1 kie_2"
    assert fields[4] == "fail: timeout; then dropped"


def test_fr203_the_file_is_utf8_with_lf_newlines(tmp_path: Path) -> None:
    """FR-256: an explicit UTF-8 encoding and no CRLF translation, so a Czech asset id round-trips
    byte for byte on Windows."""
    ledger = Ledger(tmp_path)
    ledger.intent("Li_img_prilis-zlutoucky_analyzed_01", "req-ěščř")

    blob = (tmp_path / LEDGER_FILE).read_bytes()
    assert b"\r\n" not in blob
    assert blob.endswith(b"\n")
    assert "req-ěščř" in blob.decode("utf-8")


def test_fr203_a_line_is_on_disk_before_the_call_it_describes_could_return(
    tmp_path: Path,
) -> None:
    """"Each line is opened, appended and closed, so it is on disk before the call it describes
    goes out" — the ledger is worthless if it is still in a buffer when the process is killed."""
    ledger = Ledger(tmp_path)
    ledger.intent("Li_img_dance_analyzed_01", "req-0001")

    # read through a completely separate handle, mid-run, with the Ledger object still alive
    assert "req-0001" in (tmp_path / LEDGER_FILE).read_text(encoding="utf-8")
    ledger.submitted("Li_img_dance_analyzed_01", "req-0001", "kie_1")
    assert "kie_1" in (tmp_path / LEDGER_FILE).read_text(encoding="utf-8")
