from fastapi.testclient import TestClient

from chronicle.api import create_app


def test_no_auth_by_default(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), api_token=None)
    client = TestClient(app)
    resp = client.post("/traces", json={"agent_id": "a1", "decision": "d", "outcome": "executed"})
    assert resp.status_code == 200


def test_rejects_missing_token_when_configured(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), api_token="secret123")
    client = TestClient(app)
    resp = client.post("/traces", json={"agent_id": "a1", "decision": "d", "outcome": "executed"})
    assert resp.status_code == 401


def test_rejects_malformed_auth_header(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), api_token="secret123")
    client = TestClient(app)
    resp = client.get("/traces", headers={"Authorization": "secret123"})  # missing "Bearer " prefix
    assert resp.status_code == 401


def test_rejects_wrong_token(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), api_token="secret123")
    client = TestClient(app)
    resp = client.get("/traces", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_accepts_correct_token(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), api_token="secret123")
    client = TestClient(app)
    resp = client.post(
        "/traces",
        json={"agent_id": "a1", "decision": "d", "outcome": "executed"},
        headers={"Authorization": "Bearer secret123"},
    )
    assert resp.status_code == 200


def test_all_protected_routes_enforce_auth(tmp_path):
    open_app = create_app(db_path=str(tmp_path / "a.db"), api_token=None)
    open_client = TestClient(open_app)
    open_client.post("/traces", json={"agent_id": "a1", "decision": "d", "outcome": "executed", "correlation_id": "c1"})

    app = create_app(db_path=str(tmp_path / "a.db"), api_token="secret123")
    client = TestClient(app)
    assert client.get("/traces").status_code == 401
    assert client.get("/traces/c1/chain").status_code == 401
    assert client.get("/traces/c1/replay").status_code == 401
    assert client.get("/integrity").status_code == 401


def test_health_never_requires_auth(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), api_token="secret123")
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_env_var_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONICLE_API_TOKEN", "from-env")
    app = create_app(db_path=str(tmp_path / "a.db"))  # api_token omitted entirely
    client = TestClient(app)
    assert client.get("/traces", headers={"Authorization": "Bearer from-env"}).status_code == 200
    assert client.get("/traces").status_code == 401


def test_explicit_none_overrides_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONICLE_API_TOKEN", "from-env")
    app = create_app(db_path=str(tmp_path / "a.db"), api_token=None)
    client = TestClient(app)
    assert client.get("/traces").status_code == 200
