import threading

from chronicle.models import DecisionOutcome
from chronicle.recorder import Recorder


def test_concurrent_writes_all_succeed_and_chain_valid(tmp_path):
    db_path = str(tmp_path / "conc1.db")
    recorder = Recorder(db_path=db_path)
    errors = []

    def writer(i):
        try:
            for j in range(10):
                recorder.record(
                    agent_id=f"agent-{i}",
                    decision=f"action-{j}",
                    outcome=DecisionOutcome.EXECUTED,
                    correlation_id=f"task-{i}",
                )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    report = recorder.verify_integrity()
    assert report.is_valid
    assert report.total_records == 80


def test_concurrent_writes_no_duplicate_seq(tmp_path):
    db_path = str(tmp_path / "conc2.db")
    recorder = Recorder(db_path=db_path)

    def writer(i):
        for j in range(5):
            recorder.record(
                agent_id=f"a{i}",
                decision=f"d{j}",
                outcome=DecisionOutcome.EXECUTED,
                correlation_id=f"t{i}",
            )

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    records = recorder.query(limit=1000)
    seqs = [r.seq for r in records]
    assert len(seqs) == len(set(seqs))
    assert len(seqs) == 30
