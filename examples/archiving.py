"""Run with: python3 examples/archiving.py

Seeds 6 records, archives and prunes the first 3, then proves the archive
file plus the live remainder still form one continuous, verifiable chain --
even though the first half no longer exists in the live database.
"""
from chronicle import DecisionOutcome, Recorder
from chronicle.archive import verify_archive

DB_PATH = "/tmp/chronicle_archiving_example.db"
ARCHIVE_PATH = "/tmp/chronicle_archiving_example.jsonl"

recorder = Recorder(db_path=DB_PATH)

for i in range(6):
    recorder.record(
        agent_id="deploy-agent",
        decision=f"step {i}",
        outcome=DecisionOutcome.EXECUTED,
        correlation_id="six-step-rollout",
    )

print(f"live records before archiving: {len(recorder.query(limit=100))}")

deleted = recorder.archive_and_prune(ARCHIVE_PATH, up_to_seq=3)
print(f"archived and pruned: {deleted}")
print(f"live records after archiving:  {len(recorder.query(limit=100))}")

archive_report = verify_archive(ARCHIVE_PATH)
print(f"\narchive file alone -- valid={archive_report.is_valid}, records={archive_report.total_records}")

live_report = recorder.verify_integrity()
print(f"live store alone   -- valid={live_report.is_valid}, anchored_at_genesis={live_report.anchored_at_genesis} "
      f"(self-consistent on its own, but can't prove genesis without the archive)")

continuity_report = recorder.verify_continuity(ARCHIVE_PATH)
print(f"archive + live joined -- valid={continuity_report.is_valid}, "
      f"anchored_at_genesis={continuity_report.anchored_at_genesis}, "
      f"records={continuity_report.total_records} (this is the real end-to-end proof)")
