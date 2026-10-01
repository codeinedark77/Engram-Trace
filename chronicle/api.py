from __future__ import annotations

import os
import secrets
from typing import Optional, Union

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from .models import DecisionOutcome
from .recorder import Recorder
from .replay import replay_chain

_UNSET = object()


class RecordIn(BaseModel):
    agent_id: str
    decision: str
    outcome: DecisionOutcome
    correlation_id: Optional[str] = None
    reasoning: Optional[str] = None
    inputs: Optional[dict] = None
    parent_trace_id: Optional[str] = None
    metadata: Optional[dict] = None


def _make_auth_dependency(api_token: Optional[str]):
    """Bearer-token check, fail closed. If api_token is None, auth is not
    configured and every request passes -- an explicit, visible choice made
    by the caller of create_app(), not a silent default. If api_token is
    set, every protected request must present a matching token; comparison
    uses secrets.compare_digest to avoid a timing side-channel.
    """

    def verify_token(authorization: Optional[str] = Header(default=None)) -> None:
        if api_token is None:
            return
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization[len("Bearer ") :]
        if not secrets.compare_digest(token, api_token):
            raise HTTPException(status_code=401, detail="invalid token")

    return verify_token


def create_app(db_path: str = "chronicle.db", api_token: Union[str, None, object] = _UNSET) -> FastAPI:
    """Build the Chronicle API.

    api_token controls auth on every route except /health:
      - omitted (default): falls back to the CHRONICLE_API_TOKEN env var,
        which is None (no auth) if that var isn't set
      - a string: requests must send Authorization: Bearer <that string>
      - explicit None: auth is force-disabled even if the env var is set
        (mainly for tests and local-only dev)
    """
    if api_token is _UNSET:
        api_token = os.environ.get("CHRONICLE_API_TOKEN") or None

    app = FastAPI(title="Chronicle", version="0.4.0")
    recorder = Recorder(db_path=db_path)
    protected = APIRouter(dependencies=[Depends(_make_auth_dependency(api_token))])

    @protected.post("/traces")
    def create_trace(body: RecordIn):
        record = recorder.record(**body.model_dump())
        return record.to_dict()

    @protected.get("/traces")
    def list_traces(
        agent_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        outcome: Optional[DecisionOutcome] = None,
        limit: int = Query(default=200, le=2000),
    ):
        records = recorder.query(agent_id=agent_id, correlation_id=correlation_id, outcome=outcome, limit=limit)
        return [r.to_dict() for r in records]

    @protected.get("/traces/{correlation_id}/chain")
    def get_chain(correlation_id: str):
        records = recorder.get_chain(correlation_id)
        if not records:
            raise HTTPException(status_code=404, detail="no records for this correlation_id")
        return [r.to_dict() for r in records]

    @protected.get("/traces/{correlation_id}/replay")
    def get_replay(correlation_id: str):
        records = recorder.get_chain(correlation_id)
        if not records:
            raise HTTPException(status_code=404, detail="no records for this correlation_id")
        return {"markdown": replay_chain(records)}

    @protected.get("/integrity")
    def integrity():
        report = recorder.verify_integrity()
        return report.__dict__

    app.include_router(protected)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
