"""Run with: python3 examples/basic_usage.py

Simulates a planner proposing an action, Safety Guardian approving it, and
the action executing — then replays the chain and verifies integrity live,
including a deliberate tamper to show detection actually firing.
"""
import sqlite3

from chronicle import DecisionOutcome, Recorder, replay_chain

recorder = Recorder(db_path="/tmp/chronicle_example.db")
correlation_id = "rollout-2026-08-10"

proposal = recorder.record(
    agent_id="planner-01",
    decision="propose deploying agent-harness to production",
    outcome=DecisionOutcome.PROPOSED,
    correlation_id=correlation_id,
    reasoning="all 123 tests green, canary window looks clean",
)

approval = recorder.record(
    agent_id="safety-guardian",
    decision="approve deployment",
    outcome=DecisionOutcome.APPROVED,
    correlation_id=correlation_id,
    parent_trace_id=proposal.trace_id,
    reasoning="within declared scope, no policy violations",
)

recorder.record(
    agent_id="deploy-agent",
    decision="deployed agent-harness v1.0",
    outcome=DecisionOutcome.EXECUTED,
    correlation_id=correlation_id,
    parent_trace_id=approval.trace_id,
)

print(replay_chain(recorder.get_chain(correlation_id)))
print()

report = recorder.verify_integrity()
print(f"Integrity before tampering: valid={report.is_valid}, records={report.total_records}")

# Simulate someone editing history directly in the database.
conn = sqlite3.connect("/tmp/chronicle_example.db")
conn.execute("UPDATE traces SET decision = 'silently approved everything' WHERE seq = 2")
conn.commit()
conn.close()

report = recorder.verify_integrity()
print(f"Integrity after tampering:  valid={report.is_valid}, broke at seq={report.first_break_seq}")
