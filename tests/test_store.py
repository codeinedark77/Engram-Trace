from chronicle.models import DecisionOutcome, TraceRecord
from chronicle.store import GENESIS_HASH, ChronicleStore


def make_store(tmp_path, name="s.db"):
    return ChronicleStore(str(tmp_path / name))


def test_insert_and_retrieve(tmp_path):
    store = make_store(tmp_path)
    rec = TraceRecord(agent_id="a1", decision="d1", outcome=DecisionOutcome.EXECUTED, correlation_id="c1")
    stored = store.insert(rec)
    assert stored.seq == 1
    results = store.query()
    assert len(results) == 1
    assert results[0].decision == "d1"


def test_hash_chain_links(tmp_path):
    store = make_store(tmp_path)
    r1 = store.insert(TraceRecord(agent_id="a1", decision="d1", outcome=DecisionOutcome.EXECUTED, correlation_id="c1"))
    r2 = store.insert(TraceRecord(agent_id="a1", decision="d2", outcome=DecisionOutcome.EXECUTED, correlation_id="c1"))
    assert r2.prev_hash == r1.record_hash
    assert r1.record_hash != r2.record_hash


def test_genesis_hash_first_record(tmp_path):
    store = make_store(tmp_path)
    r1 = store.insert(TraceRecord(agent_id="a1", decision="d1", outcome=DecisionOutcome.EXECUTED, correlation_id="c1"))
    assert r1.prev_hash == GENESIS_HASH


def test_query_by_agent_id(tmp_path):
    store = make_store(tmp_path)
    store.insert(TraceRecord(agent_id="a1", decision="d1", outcome=DecisionOutcome.EXECUTED, correlation_id="c1"))
    store.insert(TraceRecord(agent_id="a2", decision="d2", outcome=DecisionOutcome.EXECUTED, correlation_id="c1"))
    results = store.query(agent_id="a1")
    assert len(results) == 1
    assert results[0].agent_id == "a1"


def test_query_by_correlation_id(tmp_path):
    store = make_store(tmp_path)
    store.insert(TraceRecord(agent_id="a1", decision="d1", outcome=DecisionOutcome.EXECUTED, correlation_id="c1"))
    store.insert(TraceRecord(agent_id="a1", decision="d2", outcome=DecisionOutcome.EXECUTED, correlation_id="c2"))
    results = store.query(correlation_id="c1")
    assert len(results) == 1


def test_query_by_outcome(tmp_path):
    store = make_store(tmp_path)
    store.insert(TraceRecord(agent_id="a1", decision="d1", outcome=DecisionOutcome.DENIED, correlation_id="c1"))
    store.insert(TraceRecord(agent_id="a1", decision="d2", outcome=DecisionOutcome.EXECUTED, correlation_id="c1"))
    results = store.query(outcome=DecisionOutcome.DENIED)
    assert len(results) == 1
    assert results[0].decision == "d1"


def test_query_respects_limit(tmp_path):
    store = make_store(tmp_path)
    for i in range(5):
        store.insert(
            TraceRecord(agent_id="a1", decision=f"d{i}", outcome=DecisionOutcome.EXECUTED, correlation_id="c1")
        )
    results = store.query(limit=3)
    assert len(results) == 3


def test_wal_mode_enabled(tmp_path):
    store = make_store(tmp_path)
    mode = store._connect().execute("PRAGMA journal_mode;").fetchone()[0]
    assert mode.lower() == "wal"


def test_all_records_respects_to_seq(tmp_path):
    store = make_store(tmp_path)
    for i in range(5):
        store.insert(
            TraceRecord(agent_id="a1", decision=f"d{i}", outcome=DecisionOutcome.EXECUTED, correlation_id="c1")
        )
    records = list(store.all_records(from_seq=0, to_seq=3))
    assert [r.seq for r in records] == [1, 2, 3]


def test_query_by_time_range(tmp_path):
    store = make_store(tmp_path)
    store.insert(
        TraceRecord(
            agent_id="a1",
            decision="early",
            outcome=DecisionOutcome.EXECUTED,
            correlation_id="c1",
            timestamp="2026-01-01T00:00:00+00:00",
        )
    )
    store.insert(
        TraceRecord(
            agent_id="a1",
            decision="mid",
            outcome=DecisionOutcome.EXECUTED,
            correlation_id="c1",
            timestamp="2026-06-01T00:00:00+00:00",
        )
    )
    store.insert(
        TraceRecord(
            agent_id="a1",
            decision="late",
            outcome=DecisionOutcome.EXECUTED,
            correlation_id="c1",
            timestamp="2026-12-01T00:00:00+00:00",
        )
    )
    results = store.query(since="2026-03-01T00:00:00+00:00", until="2026-09-01T00:00:00+00:00")
    assert [r.decision for r in results] == ["mid"]


def test_insert_rolls_back_on_duplicate_trace_id(tmp_path):
    store = make_store(tmp_path)
    rec = TraceRecord(
        agent_id="a1", decision="d1", outcome=DecisionOutcome.EXECUTED, correlation_id="c1", trace_id="fixed-id"
    )
    store.insert(rec)

    dupe = TraceRecord(
        agent_id="a1", decision="d2", outcome=DecisionOutcome.EXECUTED, correlation_id="c1", trace_id="fixed-id"
    )
    try:
        store.insert(dupe)
        assert False, "expected a UNIQUE constraint violation"
    except Exception:
        pass

    # the failed insert must not have left a dangling write lock or a partial row
    conn = store._connect()
    conn.execute("BEGIN IMMEDIATE;")
    conn.execute("ROLLBACK;")
    assert len(store.query()) == 1
