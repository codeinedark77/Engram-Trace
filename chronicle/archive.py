from __future__ import annotations

import json
from typing import Optional

from .models import DecisionOutcome, TraceRecord
from .store import GENESIS_HASH, ChronicleStore
from .verify import IntegrityReport, walk_chain


def export_range(store: ChronicleStore, path: str, up_to_seq: int) -> int:
    """Write every record with seq <= up_to_seq to a JSONL file, one record
    per line, in seq order. Returns the number of records written."""
    records = list(store.all_records(from_seq=0, to_seq=up_to_seq))
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r.to_dict()) + "\n")
    return len(records)


def _load_archive(path: str) -> list[TraceRecord]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            records.append(
                TraceRecord(
                    seq=d["seq"],
                    trace_id=d["trace_id"],
                    correlation_id=d["correlation_id"],
                    agent_id=d["agent_id"],
                    parent_trace_id=d["parent_trace_id"],
                    timestamp=d["timestamp"],
                    decision=d["decision"],
                    reasoning=d["reasoning"],
                    inputs=d["inputs"],
                    outcome=DecisionOutcome(d["outcome"]),
                    metadata=d["metadata"],
                    prev_hash=d["prev_hash"],
                    record_hash=d["record_hash"],
                )
            )
    return records


def verify_archive(path: str) -> IntegrityReport:
    """Verify a JSONL archive is an internally consistent hash chain
    starting from genesis, exactly the same check as verify_integrity runs
    against a live store. An archive always starts its own check from true
    GENESIS_HASH, so a valid archive is always anchored_at_genesis=True."""
    report = walk_chain(_load_archive(path), GENESIS_HASH)
    report.anchored_at_genesis = True
    return report


def prune(store: ChronicleStore, up_to_seq: int) -> int:
    """Delete every record with seq <= up_to_seq from the live store.
    Does not archive first -- see archive_and_prune for the safe path."""
    conn = store._connect()
    conn.execute("BEGIN IMMEDIATE;")
    try:
        cur = conn.execute("DELETE FROM traces WHERE seq <= ?", (up_to_seq,))
        deleted = cur.rowcount
        conn.execute("COMMIT;")
        return deleted
    except Exception:
        conn.execute("ROLLBACK;")
        raise


def archive_and_prune(store: ChronicleStore, path: str, up_to_seq: int) -> int:
    """Export to `path`, re-read and independently verify that file, and
    only then prune the exported range from the live store. Refuses to
    delete anything it hasn't successfully re-read and verified from disk
    first -- fail closed, same as everywhere else in this system. Returns
    the number of records pruned (0 if up_to_seq matched nothing)."""
    written = export_range(store, path, up_to_seq)
    if written == 0:
        return 0
    report = verify_archive(path)
    if not report.is_valid:
        raise RuntimeError(f"refusing to prune: archive at {path} failed to verify ({report.detail})")
    return prune(store, up_to_seq)


def verify_continuity(archive_path: str, store: ChronicleStore) -> IntegrityReport:
    """Verify an archive file and the live store's remaining chain together
    form one continuous, fully-verifiable history, even though the early
    portion now lives only in the archive file on disk."""
    archive_report = verify_archive(archive_path)
    if not archive_report.is_valid:
        return IntegrityReport(
            is_valid=False,
            total_records=archive_report.total_records,
            first_break_seq=archive_report.first_break_seq,
            detail=f"archive invalid: {archive_report.detail}",
        )

    live_records = list(store.all_records(from_seq=0))
    live_report = walk_chain(live_records, archive_report.last_record_hash)

    total = archive_report.total_records + live_report.total_records
    if not live_report.is_valid:
        return IntegrityReport(
            is_valid=False,
            total_records=total,
            first_break_seq=live_report.first_break_seq,
            detail=live_report.detail,
        )
    return IntegrityReport(is_valid=True, total_records=total, anchored_at_genesis=True)
