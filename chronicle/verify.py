from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import TraceRecord
from .store import GENESIS_HASH, ChronicleStore


@dataclass
class IntegrityReport:
    is_valid: bool
    total_records: int
    first_break_seq: Optional[int] = None
    detail: Optional[str] = None
    last_record_hash: Optional[str] = None
    # True only when this check independently confirmed the chain traces
    # all the way back to true genesis. False means the chain is internally
    # self-consistent from wherever it starts, but that starting point was
    # trusted rather than proven -- typically because earlier history was
    # pruned. None means "not applicable" (e.g. a raw walk_chain call with
    # no genesis claim either way).
    anchored_at_genesis: Optional[bool] = None


def walk_chain(records: list[TraceRecord], expected_prev: str) -> IntegrityReport:
    """Core verification: recompute every record's hash from its stored
    contents and confirm each one links to the last, starting from
    `expected_prev`. Shared by live-store verification and archive
    verification so both run exactly the same check. Does not itself judge
    whether `expected_prev` is a trustworthy anchor -- callers set
    anchored_at_genesis based on how they obtained that starting hash.
    """
    if not records:
        return IntegrityReport(is_valid=True, total_records=0, last_record_hash=expected_prev)

    for rec in records:
        if rec.prev_hash != expected_prev:
            return IntegrityReport(
                is_valid=False,
                total_records=len(records),
                first_break_seq=rec.seq,
                detail=f"prev_hash mismatch at seq={rec.seq}: expected {expected_prev}, found {rec.prev_hash}",
            )
        recomputed = ChronicleStore._hash_record(rec.prev_hash, rec.canonical_payload())
        if recomputed != rec.record_hash:
            return IntegrityReport(
                is_valid=False,
                total_records=len(records),
                first_break_seq=rec.seq,
                detail=f"record_hash mismatch at seq={rec.seq}: stored content does not match its own hash",
            )
        expected_prev = rec.record_hash

    return IntegrityReport(is_valid=True, total_records=len(records), last_record_hash=expected_prev)


def verify_integrity(store: ChronicleStore, from_seq: int = 0) -> IntegrityReport:
    """Verify the live store's chain. If the earliest record currently in
    the store really is seq=1, this independently confirms the whole chain
    back to true genesis (anchored_at_genesis=True). If seq=1 has been
    pruned (or the caller asked to start partway through with from_seq),
    the earliest record's own prev_hash is trusted as the starting point:
    the result can still be is_valid=True (everything from there forward is
    self-consistent) but anchored_at_genesis=False, since nothing here
    proves that starting hash is genuine. Use verify_continuity() against
    the archive to get a real anchored proof after pruning.
    """
    records = list(store.all_records(from_seq=from_seq))
    if not records:
        report = walk_chain(records, GENESIS_HASH)
        report.anchored_at_genesis = from_seq == 0
        return report

    first = records[0]
    if from_seq == 0 and first.seq == 1:
        start_hash = GENESIS_HASH
        anchored = True
    else:
        start_hash = first.prev_hash
        anchored = False

    report = walk_chain(records, start_hash)
    report.anchored_at_genesis = anchored
    return report
