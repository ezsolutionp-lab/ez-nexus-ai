"""
Background execution of orchestrated runs. Uses a file database with a normal connection pool (not StaticPool)
because a worker thread and the request thread genuinely run at the same time.
"""

import warnings

import pytest

FAKE_AWS_KEY = "AK" + "IA" + "ABCDEFGHIJKLMNOP"   # built at runtime so no credential-shaped literal is committed

warnings.filterwarnings("ignore")

pytestmark = pytest.mark.regression


@pytest.fixture(scope="module")
def app_and_client(tmp_path_factory):
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2] / "backend"
    db_path = tmp_path_factory.mktemp("platdb") / "plat.db"
    url = f"sqlite:///{db_path}"
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                   cwd=str(backend), env={**os.environ, "DATABASE_URL": url},
                   capture_output=True, text=True, check=True)

    os.environ["DATABASE_URL"] = url
    os.environ["MO_BUILDER_WORKSPACE"] = str(tmp_path_factory.mktemp("ws"))

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    engine = create_engine(url, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=engine)

    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app

    def override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    yield app, TestClient(app), SessionLocal
    app.dependency_overrides.clear()


def _token(SessionLocal, email: str, tenant: str, *, admin: bool) -> dict:
    from app import models
    from app.auth import create_access_token, hash_password

    db = SessionLocal()
    if db.query(models.User).filter(models.User.email == email).first() is None:
        db.add(models.User(email=email, full_name=email.split("@")[0],
                           hashed_password=hash_password("x" * 16), is_admin=admin,
                           is_active=True, plan="enterprise", tenant_id=tenant))
        db.commit()
    db.close()
    tok = create_access_token({"sub": email, "is_admin": admin, "mfa": True})
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def auth(app_and_client):
    return _token(app_and_client[2], "plat-admin@example.com", "tnt-plat-a", admin=True)


@pytest.fixture(scope="module")
def other(app_and_client):
    return _token(app_and_client[2], "plat-other@example.com", "tnt-plat-b", admin=True)


@pytest.fixture(scope="module")
def member(app_and_client):
    return _token(app_and_client[2], "plat-member@example.com", "tnt-plat-a", admin=False)


import threading
import time

P = "/api/mo/platform"
GATE = threading.Event()
STARTED = []


@pytest.fixture(autouse=True)
def _tools():
    from app.mo.errors import MoResult
    from app.mo.tools.spec import RiskLevel, ToolSpec, get_tool_registry
    GATE.clear(); STARTED.clear()

    def slow(ctx, p):
        STARTED.append(p["n"])
        GATE.wait(timeout=10)
        return MoResult.ok({"n": p["n"]})
    get_tool_registry().register(ToolSpec("t.slow", "waits for a gate", slow, risk_level=RiskLevel.LOW, timeout_seconds=20,
                                          input_schema={"type": "object", "properties": {"n": {"type": "integer"}}}))
    yield
    GATE.set()


def _plan(n=1):
    return {"name": "bg-plan", "steps": [{"key": "a", "kind": "tool", "target": "t.slow", "input": {"n": n}}]}


def _wait(c, headers, rid, want, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        st = c.get(f"{P}/runs/{rid}", headers=headers).json()["status"]
        if st in want:
            return st
        time.sleep(0.05)
    raise AssertionError(f"run never reached {want}; last status {st}")


def _allow(c, auth):
    assert c.put(P + "/autonomy", headers=auth, json={"subject": "t.slow", "level": 2, "reason": "test"}).status_code == 200


def test_execute_in_background_returns_at_once_and_progress_is_visible(app_and_client, auth):
    _, c, _ = app_and_client
    _allow(c, auth)
    rid = c.post(P + "/runs", headers=auth, json=_plan()).json()["data"]["run_id"]
    started = time.time()
    r = c.post(f"{P}/runs/{rid}/execute", headers=auth, json={"background": True})
    assert r.status_code == 202 and r.json()["state"] == "QUEUED" and time.time() - started < 2
    assert _wait(c, auth, rid, {"RUNNING"}) == "RUNNING" and STARTED == [1]
    GATE.set()
    assert _wait(c, auth, rid, {"SUCCEEDED"}) == "SUCCEEDED"


def test_a_run_cannot_be_started_twice(app_and_client, auth):
    _, c, _ = app_and_client
    _allow(c, auth)
    rid = c.post(P + "/runs", headers=auth, json=_plan(2)).json()["data"]["run_id"]
    assert c.post(f"{P}/runs/{rid}/execute", headers=auth, json={"background": True}).status_code == 202
    again = c.post(f"{P}/runs/{rid}/execute", headers=auth, json={"background": True})
    assert again.status_code == 409 and "cannot be queued" in again.json()["detail"]
    GATE.set()
    _wait(c, auth, rid, {"SUCCEEDED"})
    assert STARTED == [2]                                     # the tool ran exactly once


def test_background_runs_still_stop_for_approval_at_default_autonomy(app_and_client, auth):
    _, c, _ = app_and_client
    c.put(P + "/autonomy", headers=auth, json={"subject": "t.slow", "level": 1})
    rid = c.post(P + "/runs", headers=auth, json=_plan(3)).json()["data"]["run_id"]
    assert c.post(f"{P}/runs/{rid}/execute", headers=auth, json={"background": True}).status_code == 202
    assert _wait(c, auth, rid, {"AWAITING_APPROVAL", "SUCCEEDED", "FAILED"}) == "AWAITING_APPROVAL" and STARTED == []


def test_background_is_tenant_isolated_and_authenticated(app_and_client, auth, other):
    _, c, _ = app_and_client
    _allow(c, auth)
    rid = c.post(P + "/runs", headers=auth, json=_plan(4)).json()["data"]["run_id"]
    assert c.post(f"{P}/runs/{rid}/execute", headers=other, json={"background": True}).status_code == 404
    assert c.post(f"{P}/runs/{rid}/execute", json={"background": True}).status_code == 401
    assert STARTED == []
    GATE.set()


def test_cancel_while_running_stops_the_run(app_and_client, auth):
    _, c, _ = app_and_client
    _allow(c, auth)
    plan = {"name": "bg-plan", "steps": [{"key": "a", "kind": "tool", "target": "t.slow", "input": {"n": 5}},
                                        {"key": "b", "kind": "tool", "target": "t.slow", "input": {"n": 6}, "depends_on": ["a"]}]}
    rid = c.post(P + "/runs", headers=auth, json=plan).json()["data"]["run_id"]
    c.post(f"{P}/runs/{rid}/execute", headers=auth, json={"background": True})
    _wait(c, auth, rid, {"RUNNING"})
    assert c.post(f"{P}/runs/{rid}/cancel", headers=auth).status_code == 200
    GATE.set()
    time.sleep(0.5)
    assert c.get(f"{P}/runs/{rid}", headers=auth).json()["status"] == "CANCELLED" and 6 not in STARTED


def test_a_crashed_worker_marks_the_run_failed_and_resumable(app_and_client, auth, monkeypatch):
    from app.mo.orchestration import runner
    _, c, _ = app_and_client
    _allow(c, auth)
    rid = c.post(P + "/runs", headers=auth, json=_plan(7)).json()["data"]["run_id"]
    monkeypatch.setattr(runner.Orchestrator, "execute", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    c.post(f"{P}/runs/{rid}/execute", headers=auth, json={"background": True})
    assert _wait(c, auth, rid, {"FAILED"}) == "FAILED"
    body = c.get(f"{P}/runs/{rid}", headers=auth).json()
    assert "worker crashed" in body["detail"] and "RuntimeError" in body["detail"]
    monkeypatch.undo()
    GATE.set()
    assert c.post(f"{P}/runs/{rid}/execute", headers=auth, json={"background": True}).status_code == 202
    assert _wait(c, auth, rid, {"SUCCEEDED"}) == "SUCCEEDED"


def test_restart_recovery_marks_stuck_runs_failed(app_and_client, auth):
    from app.mo.db import OrchestrationRun
    from app.mo.orchestration.background import recover_interrupted
    _, c, Session = app_and_client
    rid = c.post(P + "/runs", headers=auth, json=_plan(8)).json()["data"]["run_id"]
    db = Session()
    db.get(OrchestrationRun, rid).status = "RUNNING"
    db.commit()
    assert recover_interrupted(db) >= 1
    row = Session().get(OrchestrationRun, rid)
    assert row.status == "FAILED" and "Interrupted by a restart" in row.detail
