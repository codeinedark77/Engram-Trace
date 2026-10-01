from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from typing import Iterable, Optional

from .models import DecisionOutcome, TraceRecord

GENESIS_HASH = "0" * 64

SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT UNIQUE NOT NULL,
    correlation_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    parent_trace_id TEXT,
    timestamp TEXT NOT NULL,
    decision TEXT NOT NULL,
    reasoning TEXT,
    inputs TEXT NOT NULL,
    outcome TEXT NOT NULL,
    metadata TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    record_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traces_agent ON traces(agent_id);
CREATE INDEX IF NOT EXISTS idx_traces_correlation ON traces(correlation_id);
CREATE INDEX IF NOT EXISTS idx_traces_outcome ON traces(outcome);
CREATE INDEX IF NOT EXISTS idx_traces_timestamp ON traces(timestamp);
"""

_COLUMNS = (
    "seq, trace_id, correlation_id, agent_id, parent_trace_id, timestamp, "
    "decision, reasoning, inputs, outcome, metadata, prev_hash, record_hash"
)


class ChronicleStore:
    """SQLite-backed, hash-chained append-only store for agent decision traces.

    Each thread gets its own connection (SQLite connections aren't safe to
    share across threads); writers still serialize correctly because every
    insert takes an immediate write lock on the shared file before reading
    the previous hash, closing the same read-then-write race we hit fixing
    Companion's approve/deny path.
    """

    def __init__(self, db_path: str = "chronicle.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        self._connect().executescript(SCHEMA)

    @staticmethod
    def _hash_record(prev_hash: str, canonical_payload: str) -> str:
        h = hashlib.sha256()
        h.update(prev_hash.encode("utf-8"))
        h.update(canonical_payload.encode("utf-8"))
        return h.hexdigest()

    def insert(self, record: TraceRecord) -> TraceRecord:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE;")
        try:
            row = conn.execute("SELECT record_hash FROM traces ORDER BY seq DESC LIMIT 1").fetchone()
            prev_hash = row[0] if row else GENESIS_HASH
            record.prev_hash = prev_hash
            record.record_hash = self._hash_record(prev_hash, record.canonical_payload())

            conn.execute(
                """INSERT INTO traces
                   (trace_id, correlation_id, agent_id, parent_trace_id, timestamp,
                    decision, reasoning, inputs, outcome, metadata, prev_hash, record_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.trace_id,
                    record.correlation_id,
                    record.agent_id,
                    record.parent_trace_id,
                    record.timestamp,
                    record.decision,
                    record.reasoning,
                    json.dumps(record.inputs, sort_keys=True),
                    record.outcome.value if isinstance(record.outcome, DecisionOutcome) else record.outcome,
                    json.dumps(record.metadata, sort_keys=True),
                    record.prev_hash,
                    record.record_hash,
                ),
            )
            seq = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("COMMIT;")
            record.seq = seq
            return record
        except Exception:
            conn.execute("ROLLBACK;")
            raise

    def _row_to_record(self, row) -> TraceRecord:
        (
            seq,
            trace_id,
            correlation_id,
            agent_id,
            parent_trace_id,
            timestamp,
            decision,
            reasoning,
            inputs,
            outcome,
            metadata,
            prev_hash,
            record_hash,
        ) = row
        return TraceRecord(
            seq=seq,
            trace_id=trace_id,
            correlation_id=correlation_id,
            agent_id=agent_id,
            parent_trace_id=parent_trace_id,
            timestamp=timestamp,
            decision=decision,
            reasoning=reasoning,
            inputs=json.loads(inputs),
            outcome=DecisionOutcome(outcome),
            metadata=json.loads(metadata),
            prev_hash=prev_hash,
            record_hash=record_hash,
        )

    def query(
        self,
        agent_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        outcome: Optional[DecisionOutcome] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 200,
    ) -> list[TraceRecord]:
        conn = self._connect()
        clauses, params = [], []
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if correlation_id:
            clauses.append("correlation_id = ?")
            params.append(correlation_id)
        if outcome:
            clauses.append("outcome = ?")
            params.append(outcome.value if isinstance(outcome, DecisionOutcome) else outcome)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp <= ?")
            params.append(until)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM traces {where} ORDER BY seq ASC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_chain(self, correlation_id: str) -> list[TraceRecord]:
        return self.query(correlation_id=correlation_id, limit=100000)

    def all_records(self, from_seq: int = 0, to_seq: Optional[int] = None) -> Iterable[TraceRecord]:
        conn = self._connect()
        if to_seq is not None:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM traces WHERE seq >= ? AND seq <= ? ORDER BY seq ASC",
                (from_seq, to_seq),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM traces WHERE seq >= ? ORDER BY seq ASC",
                (from_seq,),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]
