from fastapi.testclient import TestClient

from chronicle.api import create_app


def test_health(tmp_path):
    app = create_app(db_path=str(tmp_path / "h.db"))
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}


def test_create_and_list_trace(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"))
    client = TestClient(app)
    resp = client.post(
        "/traces",
        json={"agent_id": "a1", "decision": "do thing", "outcome": "executed", "correlation_id": "c1"},
    )
    assert resp.status_code == 200
    assert resp.json()["agent_id"] == "a1"

    resp2 = client.get("/traces", params={"agent_id": "a1"})
    assert len(resp2.json()) == 1


def test_chain_endpoint(tmp_path):
    app = create_app(db_path=str(tmp_path / "c.db"))
    client = TestClient(app)
    client.post("/traces", json={"agent_id": "a1", "decision": "d1", "outcome": "executed", "correlation_id": "c1"})
    resp = client.get("/traces/c1/chain")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_chain_404_when_missing(tmp_path):
    app = create_app(db_path=str(tmp_path / "m.db"))
    client = TestClient(app)
    resp = client.get("/traces/nope/chain")
    assert resp.status_code == 404


def test_replay_endpoint(tmp_path):
    app = create_app(db_path=str(tmp_path / "rp.db"))
    client = TestClient(app)
    client.post(
        "/traces",
        json={"agent_id": "planner", "decision": "propose X", "outcome": "proposed", "correlation_id": "c1"},
    )
    resp = client.get("/traces/c1/replay")
    assert resp.status_code == 200
    assert "planner" in resp.json()["markdown"]


def test_integrity_endpoint(tmp_path):
    app = create_app(db_path=str(tmp_path / "i.db"))
    client = TestClient(app)
    client.post("/traces", json={"agent_id": "a1", "decision": "d1", "outcome": "executed", "correlation_id": "c1"})
    resp = client.get("/integrity")
    assert resp.status_code == 200
    assert resp.json()["is_valid"] is True
