import json

import pytest

from chronicle.cli import main
from chronicle.models import DecisionOutcome
from chronicle.recorder import Recorder


def test_log_then_verify(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    rc = main(["--db", db, "log", "a1", "did a thing", "executed", "--correlation-id", "c1"])
    assert rc == 0
    assert capsys.readouterr().out.strip()  # printed a trace_id

    rc = main(["--db", db, "verify"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "VALID" in out
    assert "1 record" in out


def test_verify_json_output(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    main(["--db", db, "log", "a1", "d", "executed"])
    capsys.readouterr()
    rc = main(["--db", db, "verify", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["is_valid"] is True


def test_verify_reports_broken_chain(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    recorder = Recorder(db_path=db)
    for i in range(3):
        recorder.record(agent_id="a1", decision=f"d{i}", outcome=DecisionOutcome.EXECUTED, correlation_id="c1")
    conn = recorder.store._connect()
    conn.execute("UPDATE traces SET decision='HACKED' WHERE seq=2")

    rc = main(["--db", db, "verify"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "BROKEN" in out
    assert "seq=2" in out


def test_replay_prints_chain(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    main(["--db", db, "log", "planner", "propose X", "proposed", "--correlation-id", "c1"])
    capsys.readouterr()
    rc = main(["--db", db, "replay", "c1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "planner" in out
    assert "propose X" in out


def test_replay_missing_correlation_id_errors(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    rc = main(["--db", db, "replay", "nope"])
    assert rc == 1


def test_cli_archive_and_verify_continuity(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    for i in range(5):
        main(["--db", db, "log", "a1", f"d{i}", "executed", "--correlation-id", "c1"])
    capsys.readouterr()

    archive_path = str(tmp_path / "arch.jsonl")
    rc = main(["--db", db, "archive", archive_path, "--up-to-seq", "3"])
    assert rc == 0
    assert "archived and pruned 3" in capsys.readouterr().out

    rc = main(["--db", db, "verify", "--archive", archive_path])
    assert rc == 0
    out = capsys.readouterr().out
    assert "VALID" in out
    assert "5 record" in out


def test_cli_archive_reports_error_on_failed_verify(tmp_path, capsys, monkeypatch):
    from chronicle.recorder import Recorder as RecorderClass

    def fake_archive_and_prune(self, path, up_to_seq):
        raise RuntimeError("simulated verify failure")

    monkeypatch.setattr(RecorderClass, "archive_and_prune", fake_archive_and_prune)

    db = str(tmp_path / "cli.db")
    main(["--db", db, "log", "a1", "d", "executed"])
    capsys.readouterr()

    rc = main(["--db", db, "archive", str(tmp_path / "a.jsonl"), "--up-to-seq", "1"])
    assert rc == 1
    assert "error" in capsys.readouterr().err.lower()


def test_verify_without_archive_notes_missing_anchor_after_pruning(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    for i in range(5):
        main(["--db", db, "log", "a1", f"d{i}", "executed", "--correlation-id", "c1"])
    capsys.readouterr()

    main(["--db", db, "archive", str(tmp_path / "a.jsonl"), "--up-to-seq", "3"])
    capsys.readouterr()

    rc = main(["--db", db, "verify"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "VALID" in out
    assert "not verified back to genesis" in out


def test_token_command_prints_a_token(capsys):
    rc = main(["token"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert len(out) > 20


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "chronicle" in out.lower()


def test_log_rejects_invalid_outcome(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    try:
        main(["--db", db, "log", "a1", "d", "not-a-real-outcome"])
        assert False, "argparse should have rejected this and exited"
    except SystemExit as e:
        assert e.code != 0
