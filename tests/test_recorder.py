from chronicle.models import DecisionOutcome
from chronicle.recorder import Recorder


def test_record_creates_trace_with_generated_id(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "r.db"))
    rec = recorder.record(agent_id="a1", decision="do X", outcome=DecisionOutcome.EXECUTED, correlation_id="c1")
    assert rec.trace_id
    assert rec.seq == 1


def test_record_generates_correlation_id_when_omitted(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "r.db"))
    rec = recorder.record(agent_id="a1", decision="do X", outcome=DecisionOutcome.EXECUTED)
    assert rec.correlation_id


def test_record_accepts_string_outcome(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "r.db"))
    rec = recorder.record(agent_id="a1", decision="do X", outcome="approved", correlation_id="c1")
    assert rec.outcome == DecisionOutcome.APPROVED


def test_get_chain_orders_by_seq(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "r.db"))
    recorder.record(agent_id="a1", decision="d1", outcome=DecisionOutcome.EXECUTED, correlation_id="c1")
    recorder.record(agent_id="a1", decision="d2", outcome=DecisionOutcome.EXECUTED, correlation_id="c1")
    chain = recorder.get_chain("c1")
    assert [r.decision for r in chain] == ["d1", "d2"]


def test_get_chain_empty_for_unknown_id(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "r.db"))
    assert recorder.get_chain("nope") == []
