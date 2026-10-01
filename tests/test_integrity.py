from chronicle.models import DecisionOutcome
from chronicle.recorder import Recorder


def test_empty_store_is_valid(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "e.db"))
    report = recorder.verify_integrity()
    assert report.is_valid
    assert report.total_records == 0


def test_clean_chain_is_valid(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "c.db"))
    for i in range(4):
        recorder.record(agent_id="a1", decision=f"d{i}", outcome=DecisionOutcome.EXECUTED, correlation_id="c1")
    report = recorder.verify_integrity()
    assert report.is_valid
    assert report.total_records == 4


def test_tampered_record_detected(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "t.db"))
    for i in range(5):
        recorder.record(agent_id="a1", decision=f"d{i}", outcome=DecisionOutcome.EXECUTED, correlation_id="c1")
    conn = recorder.store._connect()
    conn.execute("UPDATE traces SET decision = 'HACKED' WHERE seq = 3")

    report = recorder.verify_integrity()
    assert not report.is_valid
    assert report.first_break_seq == 3


def test_deleted_record_detected(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "d.db"))
    for i in range(5):
        recorder.record(agent_id="a1", decision=f"d{i}", outcome=DecisionOutcome.EXECUTED, correlation_id="c1")
    conn = recorder.store._connect()
    conn.execute("DELETE FROM traces WHERE seq = 3")

    report = recorder.verify_integrity()
    assert not report.is_valid


def test_verify_integrity_from_seq_past_end_is_valid_empty(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "p.db"))
    recorder.record(agent_id="a1", decision="d1", outcome=DecisionOutcome.EXECUTED, correlation_id="c1")
    report = recorder.verify_integrity(from_seq=1000)
    assert report.is_valid
    assert report.total_records == 0


def test_verify_integrity_anchored_at_genesis_for_fresh_store(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "f.db"))
    recorder.record(agent_id="a1", decision="d1", outcome=DecisionOutcome.EXECUTED, correlation_id="c1")
    report = recorder.verify_integrity()
    assert report.is_valid
    assert report.anchored_at_genesis is True


def test_verify_integrity_after_pruning_is_valid_but_not_anchored(tmp_path):
    # regression test: a store that's had its early history legitimately
    # archived and pruned must NOT report BROKEN just because it can no
    # longer independently prove genesis on its own.
    recorder = Recorder(db_path=str(tmp_path / "pr.db"))
    for i in range(5):
        recorder.record(agent_id="a1", decision=f"d{i}", outcome=DecisionOutcome.EXECUTED, correlation_id="c1")
    recorder.archive_and_prune(str(tmp_path / "arch.jsonl"), up_to_seq=3)

    report = recorder.verify_integrity()
    assert report.is_valid
    assert report.anchored_at_genesis is False
