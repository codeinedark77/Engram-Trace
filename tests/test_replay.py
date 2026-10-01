from chronicle.models import DecisionOutcome
from chronicle.recorder import Recorder
from chronicle.replay import replay_chain


def test_empty_chain_message():
    assert "no records" in replay_chain([]).lower()


def test_chain_includes_agent_and_decision(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "r.db"))
    recorder.record(
        agent_id="planner",
        decision="propose plan X",
        outcome=DecisionOutcome.PROPOSED,
        correlation_id="t1",
        reasoning="best fit",
    )
    chain = recorder.get_chain("t1")
    md = replay_chain(chain)
    assert "planner" in md
    assert "propose plan X" in md
    assert "best fit" in md


def test_parent_child_indentation(tmp_path):
    recorder = Recorder(db_path=str(tmp_path / "r.db"))
    parent = recorder.record(
        agent_id="planner", decision="propose X", outcome=DecisionOutcome.PROPOSED, correlation_id="t1"
    )
    recorder.record(
        agent_id="guardian",
        decision="approve X",
        outcome=DecisionOutcome.APPROVED,
        correlation_id="t1",
        parent_trace_id=parent.trace_id,
    )
    chain = recorder.get_chain("t1")
    md = replay_chain(chain)
    lines = [l for l in md.splitlines() if "approve X" in l]
    assert lines and lines[0].startswith("  -")
