import pytest

from chronicle.models import DecisionOutcome
from chronicle.recorder import Recorder


def test_span_records_proposed_on_enter(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    with recorder.decision(agent_id="guardian", decision="authorize X", correlation_id="c1") as d:
        assert d.proposed_trace.outcome == DecisionOutcome.PROPOSED
    chain = recorder.get_chain("c1")
    assert chain[0].outcome == DecisionOutcome.PROPOSED


def test_span_resolve_records_final_outcome(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    with recorder.decision(agent_id="guardian", decision="authorize X", correlation_id="c1") as d:
        d.resolve(DecisionOutcome.APPROVED, reasoning="within scope")
    chain = recorder.get_chain("c1")
    assert [r.outcome for r in chain] == [DecisionOutcome.PROPOSED, DecisionOutcome.APPROVED]
    assert chain[1].parent_trace_id == chain[0].trace_id
    assert chain[1].reasoning == "within scope"


def test_span_auto_executed_if_not_resolved(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    with recorder.decision(agent_id="deploy-agent", decision="deploy v1", correlation_id="c1"):
        pass  # agent does its work, never calls resolve()
    chain = recorder.get_chain("c1")
    assert chain[-1].outcome == DecisionOutcome.EXECUTED


def test_span_records_failed_on_exception(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    with pytest.raises(ValueError):
        with recorder.decision(agent_id="deploy-agent", decision="deploy v1", correlation_id="c1"):
            raise ValueError("disk full")
    chain = recorder.get_chain("c1")
    assert chain[-1].outcome == DecisionOutcome.FAILED
    assert "disk full" in chain[-1].reasoning


def test_span_generates_correlation_id_when_omitted(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "s.db"))
    with recorder.decision(agent_id="a1", decision="do X") as d:
        cid = d.proposed_trace.correlation_id
    assert cid
    assert recorder.get_chain(cid)
