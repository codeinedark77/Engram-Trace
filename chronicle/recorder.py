from __future__ import annotations

import uuid
from typing import Optional, Union

from .archive import archive_and_prune as _archive_and_prune
from .archive import verify_continuity as _verify_continuity
from .models import DecisionOutcome, TraceRecord
from .store import ChronicleStore
from .verify import IntegrityReport, verify_integrity


class DecisionSpan:
    """Context manager that records a decision's full lifecycle in one block,
    so a call site doesn't need two separate .record() calls to capture a
    propose -> resolve arc.

        with recorder.decision(agent_id="guardian", decision="authorize deploy",
                                correlation_id=cid) as d:
            if is_safe(action):
                d.resolve(DecisionOutcome.APPROVED, reasoning="within scope")
            else:
                d.resolve(DecisionOutcome.DENIED, reasoning="scope violation")

    A clean exit without an explicit resolve() records EXECUTED. An
    exception inside the block records FAILED with the exception message as
    reasoning, then always re-raises — Chronicle only observes, it never
    swallows an error.
    """

    def __init__(
        self,
        recorder: "Recorder",
        agent_id: str,
        decision: str,
        correlation_id: Optional[str] = None,
        parent_trace_id: Optional[str] = None,
        reasoning: Optional[str] = None,
        inputs: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ):
        self._recorder = recorder
        self._agent_id = agent_id
        self._decision = decision
        self._correlation_id = correlation_id
        self._parent_trace_id = parent_trace_id
        self._reasoning = reasoning
        self._inputs = inputs
        self._metadata = metadata
        self._resolved = False
        self.proposed_trace: Optional[TraceRecord] = None

    def __enter__(self) -> "DecisionSpan":
        self.proposed_trace = self._recorder.record(
            agent_id=self._agent_id,
            decision=self._decision,
            outcome=DecisionOutcome.PROPOSED,
            correlation_id=self._correlation_id,
            parent_trace_id=self._parent_trace_id,
            reasoning=self._reasoning,
            inputs=self._inputs,
            metadata=self._metadata,
        )
        # everything else in this span chains off the PROPOSED trace and
        # shares its correlation_id, even if the caller never supplied one
        self._correlation_id = self.proposed_trace.correlation_id
        return self

    def resolve(self, outcome: Union[DecisionOutcome, str], reasoning: Optional[str] = None) -> TraceRecord:
        self._resolved = True
        return self._recorder.record(
            agent_id=self._agent_id,
            decision=self._decision,
            outcome=outcome,
            correlation_id=self._correlation_id,
            parent_trace_id=self.proposed_trace.trace_id,
            reasoning=reasoning,
        )

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.resolve(DecisionOutcome.FAILED, reasoning=str(exc))
            return None
        if not self._resolved:
            self.resolve(DecisionOutcome.EXECUTED)
        return None


class Recorder:
    """The API agents, Safety Guardian, and agent-harness call to record
    and query decision traces. Wraps a ChronicleStore."""

    def __init__(self, db_path: str = "chronicle.db"):
        self.store = ChronicleStore(db_path)

    def record(
        self,
        agent_id: str,
        decision: str,
        outcome: Union[DecisionOutcome, str],
        correlation_id: Optional[str] = None,
        reasoning: Optional[str] = None,
        inputs: Optional[dict] = None,
        parent_trace_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> TraceRecord:
        if not isinstance(outcome, DecisionOutcome):
            outcome = DecisionOutcome(outcome)
        record = TraceRecord(
            agent_id=agent_id,
            decision=decision,
            outcome=outcome,
            correlation_id=correlation_id or str(uuid.uuid4()),
            reasoning=reasoning,
            inputs=inputs or {},
            parent_trace_id=parent_trace_id,
            metadata=metadata or {},
        )
        return self.store.insert(record)

    def query(self, **filters) -> list[TraceRecord]:
        return self.store.query(**filters)

    def get_chain(self, correlation_id: str) -> list[TraceRecord]:
        return self.store.get_chain(correlation_id)

    def verify_integrity(self, from_seq: int = 0) -> IntegrityReport:
        return verify_integrity(self.store, from_seq=from_seq)

    def decision(
        self,
        agent_id: str,
        decision: str,
        correlation_id: Optional[str] = None,
        parent_trace_id: Optional[str] = None,
        reasoning: Optional[str] = None,
        inputs: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> DecisionSpan:
        return DecisionSpan(self, agent_id, decision, correlation_id, parent_trace_id, reasoning, inputs, metadata)

    def archive_and_prune(self, path: str, up_to_seq: int) -> int:
        """Export records up to up_to_seq to a JSONL file, verify that file
        independently, and only then delete those records from the live
        store. Raises RuntimeError instead of pruning if the archive fails
        to verify."""
        return _archive_and_prune(self.store, path, up_to_seq)

    def verify_continuity(self, archive_path: str) -> IntegrityReport:
        """Verify an archive file and the live store's remaining chain
        together form one continuous, fully-verifiable history."""
        return _verify_continuity(archive_path, self.store)
