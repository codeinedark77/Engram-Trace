import json

import pytest

from chronicle.archive import archive_and_prune, export_range, prune, verify_archive, verify_continuity
from chronicle.models import DecisionOutcome
from chronicle.recorder import Recorder


def _seed(recorder, n, correlation_id="c1"):
    for i in range(n):
        recorder.record(
            agent_id="a1", decision=f"d{i}", outcome=DecisionOutcome.EXECUTED, correlation_id=correlation_id
        )


def test_export_range_writes_expected_count(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    _seed(recorder, 5)
    archive_path = str(tmp_path / "archive.jsonl")
    written = export_range(recorder.store, archive_path, up_to_seq=3)
    assert written == 3
    with open(archive_path) as f:
        assert len(f.readlines()) == 3


def test_verify_archive_valid_for_clean_export(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    _seed(recorder, 5)
    archive_path = str(tmp_path / "archive.jsonl")
    export_range(recorder.store, archive_path, up_to_seq=5)
    report = verify_archive(archive_path)
    assert report.is_valid
    assert report.total_records == 5


def test_verify_archive_detects_tampering(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    _seed(recorder, 3)
    archive_path = str(tmp_path / "archive.jsonl")
    export_range(recorder.store, archive_path, up_to_seq=3)

    with open(archive_path) as f:
        lines = f.readlines()
    tampered = json.loads(lines[1])
    tampered["decision"] = "HACKED"
    lines[1] = json.dumps(tampered) + "\n"
    with open(archive_path, "w") as f:
        f.writelines(lines)

    report = verify_archive(archive_path)
    assert not report.is_valid


def test_prune_removes_records_up_to_seq(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    _seed(recorder, 5)
    deleted = prune(recorder.store, up_to_seq=3)
    assert deleted == 3
    remaining = recorder.query(limit=100)
    assert [r.seq for r in remaining] == [4, 5]


def test_archive_and_prune_end_to_end(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    _seed(recorder, 5)
    archive_path = str(tmp_path / "archive.jsonl")
    deleted = archive_and_prune(recorder.store, archive_path, up_to_seq=3)
    assert deleted == 3
    assert [r.seq for r in recorder.query(limit=100)] == [4, 5]
    report = verify_archive(archive_path)
    assert report.is_valid
    assert report.total_records == 3


def test_archive_and_prune_refuses_when_archive_fails_to_verify(tmp_path, monkeypatch):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    _seed(recorder, 3)
    archive_path = str(tmp_path / "archive.jsonl")

    import chronicle.archive as archive_mod

    original_verify = archive_mod.verify_archive

    def fake_verify(path):
        report = original_verify(path)
        report.is_valid = False
        report.detail = "simulated corruption"
        return report

    monkeypatch.setattr(archive_mod, "verify_archive", fake_verify)

    with pytest.raises(RuntimeError):
        archive_and_prune(recorder.store, archive_path, up_to_seq=3)

    # nothing should have been pruned since the (simulated) verify failed
    assert len(recorder.query(limit=100)) == 3


def test_verify_continuity_across_archive_and_live_store(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    _seed(recorder, 6)
    archive_path = str(tmp_path / "archive.jsonl")
    archive_and_prune(recorder.store, archive_path, up_to_seq=3)

    report = verify_continuity(archive_path, recorder.store)
    assert report.is_valid
    assert report.total_records == 6


def test_verify_continuity_detects_tampering_in_live_remainder(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    _seed(recorder, 6)
    archive_path = str(tmp_path / "archive.jsonl")
    archive_and_prune(recorder.store, archive_path, up_to_seq=3)

    conn = recorder.store._connect()
    conn.execute("UPDATE traces SET decision='HACKED' WHERE seq=5")

    report = verify_continuity(archive_path, recorder.store)
    assert not report.is_valid


def test_archive_and_prune_returns_zero_when_nothing_to_archive(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    _seed(recorder, 3)
    deleted = archive_and_prune(recorder.store, str(tmp_path / "empty.jsonl"), up_to_seq=0)
    assert deleted == 0
    assert len(recorder.query(limit=100)) == 3


def test_verify_continuity_reports_invalid_archive(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    _seed(recorder, 6)
    archive_path = str(tmp_path / "archive.jsonl")
    archive_and_prune(recorder.store, archive_path, up_to_seq=3)

    with open(archive_path) as f:
        lines = f.readlines()
    tampered = json.loads(lines[0])
    tampered["decision"] = "HACKED"
    lines[0] = json.dumps(tampered) + "\n"
    with open(archive_path, "w") as f:
        f.writelines(lines)

    report = verify_continuity(archive_path, recorder.store)
    assert not report.is_valid
    assert "archive invalid" in report.detail


def test_verify_archive_reports_anchored_at_genesis(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    _seed(recorder, 3)
    archive_path = str(tmp_path / "archive.jsonl")
    export_range(recorder.store, archive_path, up_to_seq=3)
    report = verify_archive(archive_path)
    assert report.anchored_at_genesis is True


def test_verify_continuity_reports_anchored_at_genesis_on_success(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    _seed(recorder, 6)
    archive_path = str(tmp_path / "archive.jsonl")
    archive_and_prune(recorder.store, archive_path, up_to_seq=3)

    report = verify_continuity(archive_path, recorder.store)
    assert report.is_valid
    assert report.anchored_at_genesis is True
