from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class DecisionOutcome(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    DENIED = "denied"
    EXECUTED = "executed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class TraceRecord:
    """One recorded decision/action taken by an agent in the empire.

    Records are chained: each one's `prev_hash` is the `record_hash` of the
    record immediately before it in the store, so the sequence can be
    walked and independently re-verified for tampering (see verify.py).
    """

    agent_id: str
    decision: str
    outcome: DecisionOutcome
    correlation_id: str
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_trace_id: Optional[str] = None
    reasoning: Optional[str] = None
    inputs: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    seq: Optional[int] = None
    prev_hash: Optional[str] = None
    record_hash: Optional[str] = None

    def canonical_payload(self) -> str:
        """Deterministic JSON used as hashing input. Excludes seq/record_hash
        (those are derived from, not inputs to, the hash)."""
        payload = {
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "agent_id": self.agent_id,
            "parent_trace_id": self.parent_trace_id,
            "timestamp": self.timestamp,
            "decision": self.decision,
            "reasoning": self.reasoning,
            "inputs": self.inputs,
            "outcome": self.outcome.value if isinstance(self.outcome, DecisionOutcome) else self.outcome,
            "metadata": self.metadata,
            "prev_hash": self.prev_hash,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["outcome"] = self.outcome.value if isinstance(self.outcome, DecisionOutcome) else self.outcome
        return d
