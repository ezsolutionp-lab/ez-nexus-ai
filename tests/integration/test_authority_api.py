"""
The authority API (capability requests, grants, gateway, receipts, releases, compliance, vault), driven
through the live app with real JWTs.
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
    from sqlalchemy.pool import StaticPool

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
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


A = "/api/mo/authority"

ROUTES = [
    ("get", "/policy"), ("post", "/capabilities/request"), ("post", "/grants"), ("post", "/execute"),
    ("get", "/receipts"), ("get", "/receipts/x"), ("get", "/traces/x"), ("post", "/council/validate"),
    ("get", "/agents"), ("post", "/agents"), ("post", "/agents/a/status"), ("post", "/agents/a/rollback"),
    ("post", "/releases"), ("get", "/releases"), ("get", "/releases/x"), ("post", "/releases/x/scan"),
    ("post", "/releases/x/eval"), ("post", "/releases/x/approval"), ("post", "/releases/x/canary"),
    ("post", "/releases/x/promote"), ("post", "/compliance/sbom"), ("get", "/compliance/dependencies"),
    ("get", "/compliance/gate"), ("post", "/compliance/dependencies/x/review"), ("post", "/vault/leases"),
    ("delete", "/vault/leases/x"),
]


@pytest.fixture(autouse=True)
def _tool():
    from app.mo.errors import MoResult
    from app.mo.tools.spec import RiskLevel, ToolSpec, get_tool_registry
    from app.mo.vault import leases
    calls = []
    get_tool_registry().register(ToolSpec(
        "t.note", "write a note", lambda c, p: (calls.append(p["text"]), MoResult.ok({"written": p["text"]}))[1],
        risk_level=RiskLevel.MEDIUM, input_schema={"type": "object", "properties": {"text": {"type": "string"}}}))
    leases.reset()
    yield calls
    leases.reset()


@pytest.mark.parametrize("method,path", ROUTES)
def test_every_authority_route_requires_authentication(app_and_client, method, path):
    _, c, _ = app_and_client
    kw = {"json": {}} if method in ("post", "put") else {}
    assert getattr(c, method)(A + path, **kw).status_code == 401


def test_policy_lists_the_fixed_deny_list(app_and_client, member):
    _, c, _ = app_and_client
    body = c.get(A + "/policy", headers=member).json()
    assert "withdraw_funds" in body["forbidden_actions"] and body["finance_policy"]["withdraw_funds"] == "DENY"
    assert "receipt" in body["council"]["mandatory_by_risk"]["write"]


def _approve_and_collect(c, member, auth, args, *, action="write_text", resource="note.txt"):
    req = c.post(A + "/capabilities/request", headers=member,
                 json={"tool": "t.note", "action": action, "resource": resource, "risk": "write", "args": args})
    assert req.status_code == 202, req.text
    aid = req.json()["data"]["approval_id"]
    assert c.post(f"/api/mo/approvals/{aid}/decide", headers=auth, json={"approve": True}).status_code == 200
    g = c.post(A + "/grants", headers=member, json={"approval_id": aid})
    assert g.status_code == 201, g.text
    return g.json()["data"]["token"]


def test_http_flow_request_approve_grant_execute_receipt(app_and_client, auth, member, _tool):
    _, c, _ = app_and_client
    body = {"tool": "t.note", "action": "write_text", "resource": "note.txt", "risk": "write", "args": {"text": "hi"}}
    refused = c.post(A + "/execute", headers=member, json=body)
    assert refused.status_code == 202 and refused.json()["state"] == "APPROVAL_REQUIRED" and _tool == []
    token = _approve_and_collect(c, member, auth, {"text": "hi"})
    ok = c.post(A + "/execute", headers=member, json={**body, "grant_token": token, "idempotency_key": "http-1"})
    assert ok.status_code == 200 and _tool == ["hi"], ok.text
    rid = ok.json()["meta"]["receipt_id"]
    rec = c.get(f"{A}/receipts/{rid}", headers=member).json()
    assert rec["success"] and rec["tool"] == "t.note" and rec["idempotency_key"] == "http-1"
    assert any(r["receipt_id"] == rid for r in c.get(A + "/receipts?tool=t.note", headers=member).json()["receipts"])
    assert any(r["receipt_id"] == rid for r in c.get(f"{A}/traces/{rec['trace_id']}", headers=member).json()["receipts"])
    replay = c.post(A + "/execute", headers=member, json={**body, "idempotency_key": "http-1"})
    assert replay.status_code == 200 and replay.json()["meta"]["replayed"] is True and _tool == ["hi"]
    reuse = c.post(A + "/execute", headers=member, json={**body, "grant_token": token})
    assert reuse.status_code == 403 and _tool == ["hi"]


def test_http_grant_rejects_changed_arguments(app_and_client, auth, member, _tool):
    _, c, _ = app_and_client
    token = _approve_and_collect(c, member, auth, {"text": "reviewed"}, resource="n2.txt")
    r = c.post(A + "/execute", headers=member, json={"tool": "t.note", "action": "write_text", "resource": "n2.txt",
                                                      "risk": "write", "args": {"text": "swapped"}, "grant_token": token})
    assert r.status_code == 403 and "mismatch" in r.json()["detail"] and _tool == []


def test_http_requester_cannot_approve_own_request(app_and_client, member):
    _, c, _ = app_and_client
    req = c.post(A + "/capabilities/request", headers=member,
                 json={"tool": "t.note", "action": "write_text", "resource": "self.txt", "risk": "write", "args": {"text": "x"}})
    aid = req.json()["data"]["approval_id"]
    assert c.post(f"/api/mo/approvals/{aid}/decide", headers=member, json={"approve": True}).status_code == 403
    assert c.post(A + "/grants", headers=member, json={"approval_id": aid}).status_code == 202


@pytest.mark.parametrize("action", ["withdraw_funds", "disable_audit", "mint_admin"])
def test_http_forbidden_actions_are_denied(app_and_client, auth, action):
    _, c, _ = app_and_client
    r = c.post(A + "/capabilities/request", headers=auth,
               json={"tool": "t.note", "action": action, "resource": "acct", "risk": "sensitive", "args": {}})
    assert r.status_code == 403 and "forbidden" in r.json()["detail"]
    run = c.post(A + "/execute", headers=auth, json={"tool": "t.note", "action": action, "resource": "acct",
                                                      "args": {"text": "x"}, "grant_token": "whatever"})
    assert run.status_code == 403


def test_http_validation(app_and_client, member):
    _, c, _ = app_and_client
    assert c.post(A + "/execute", headers=member, json={"tool": "t.note", "action": "a", "resource": "r", "risk": "root"}).status_code == 422
    assert c.post(A + "/execute", headers=member, json={"tool": "", "action": "a", "resource": "r"}).status_code == 422
    assert c.post(A + "/execute", headers=member, json={"tool": "t.note", "action": "a", "resource": "r",
                                                         "idempotency_key": "k" * 300}).status_code == 422


def test_http_receipts_are_tenant_isolated(app_and_client, auth, other, member, _tool):
    _, c, _ = app_and_client
    ok = c.post(A + "/execute", headers=member, json={"tool": "domain.route", "action": "route", "resource": "r",
                                                       "args": {"text": "invoice"}})
    assert ok.status_code == 200
    rid = ok.json()["meta"]["receipt_id"]
    assert c.get(f"{A}/receipts/{rid}", headers=other).status_code == 404
    assert all(r["receipt_id"] != rid for r in c.get(A + "/receipts", headers=other).json()["receipts"])


def test_http_council(app_and_client, member):
    _, c, _ = app_and_client
    ok = c.post(A + "/council/validate", headers=member,
                json={"risk": "read", "output": {"total": 3}, "acceptance": [{"type": "path_equals", "path": "total", "value": 3}]})
    assert ok.status_code == 200 and ok.json()["passed"] is True
    bad = c.post(A + "/council/validate", headers=member, json={"risk": "write", "output": {"a": 1},
                                                                "acceptance": [{"type": "path_present", "path": "a"}]})
    assert bad.json()["passed"] is False and "receipt" in bad.json()["failed"]
    assert c.post(A + "/council/validate", headers=member, json={"risk": "root"}).status_code == 422


def test_http_agents_and_release_flow(app_and_client, auth, member):
    _, c, _ = app_and_client
    body = {"name": "http-agent", "description": "d", "allowed_tools": ["domain.route"], "risk_ceiling": "read"}
    assert c.post(A + "/agents", headers=member, json=body).status_code == 403
    assert c.post(A + "/agents", headers=auth, json=body).status_code == 201
    assert c.post(A + "/agents", headers=auth, json=body).status_code == 409
    assert any(a["name"] == "http-agent" for a in c.get(A + "/agents", headers=member).json()["agents"])
    exe = c.post(A + "/execute", headers=member, json={"tool": "t.note", "action": "x", "resource": "r", "risk": "write",
                                                        "args": {"text": "x"}, "agent": "http-agent"})
    assert exe.status_code == 403 and "not allowed" in exe.json()["detail"]
    manifest = {"agent_version": "1", "prompt_version": "p", "model_policy_version": "m",
                "skill_manifest_hash": "h", "security_policy_version": "s"}
    rel = c.post(A + "/releases", headers=auth, json={"agent": "http-agent", "version": "1.0", "manifest": manifest})
    assert rel.status_code == 201, rel.text
    rid = rel.json()["data"]["id"]
    assert c.post(f"{A}/releases/{rid}/promote", headers=auth).status_code == 409          # gates incomplete
    scan = c.post(f"{A}/releases/{rid}/scan", headers=auth)
    assert scan.status_code == 409 and "dependencies" in scan.json()["detail"]             # nothing approved yet
    assert c.get(f"{A}/releases/{rid}", headers=auth).json()["status"] == "STOPPED"
    assert c.get(f"{A}/releases/nope", headers=auth).status_code == 404


def test_http_release_is_tenant_isolated(app_and_client, auth, other):
    _, c, _ = app_and_client
    c.post(A + "/agents", headers=auth, json={"name": "iso-agent", "allowed_tools": ["domain.route"]})
    manifest = {"agent_version": "1", "prompt_version": "p", "model_policy_version": "m",
                "skill_manifest_hash": "h", "security_policy_version": "s"}
    rid = c.post(A + "/releases", headers=auth, json={"agent": "iso-agent", "version": "1", "manifest": manifest}).json()["data"]["id"]
    assert c.get(f"{A}/releases/{rid}", headers=other).status_code == 404
    assert c.post(f"{A}/releases/{rid}/scan", headers=other).status_code == 404
    assert c.post(A + "/agents/iso-agent/status", headers=other, json={"status": "DISABLED"}).status_code == 404


def test_http_compliance_quarantine_and_review(app_and_client, auth, member):
    _, c, _ = app_and_client
    sbom = {"cyclonedx": {"components": [{"name": "unknown-lib", "version": "3", "licenses": []},
                                         {"name": "ok-lib", "version": "1", "licenses": [{"license": {"id": "MIT"}}]}]}}
    r = c.post(A + "/compliance/sbom", headers=auth, json=sbom)
    assert r.status_code == 201 and r.json()["data"]["quarantined"] == ["unknown-lib==3"]
    assert c.get(A + "/compliance/gate", headers=auth).json()["passed"] is False
    quarantined = c.get(A + "/compliance/dependencies?status=QUARANTINED", headers=auth).json()["dependencies"]
    dep = next(d for d in quarantined if d["name"] == "unknown-lib")
    assert c.post(f"{A}/compliance/dependencies/{dep['id']}/review", headers=member, json={"approve": True, "notes": "x"}).status_code == 403
    assert c.post(f"{A}/compliance/dependencies/{dep['id']}/review", headers=auth, json={"approve": True}).status_code == 422
    assert c.post(f"{A}/compliance/dependencies/{dep['id']}/review", headers=auth,
                  json={"approve": True, "notes": "Verified MIT upstream"}).status_code == 200
    assert c.get(A + "/compliance/dependencies?status=BOGUS", headers=auth).status_code == 422
    assert c.post(A + "/compliance/sbom", headers=auth, json={}).status_code == 422


def test_http_vault_never_returns_the_secret(app_and_client, member, monkeypatch):
    _, c, _ = app_and_client
    monkeypatch.setenv("MO_VAULT_SECRETS", "broker=MO_HTTP_SECRET")
    monkeypatch.delenv("MO_HTTP_SECRET", raising=False)
    assert c.post(A + "/vault/leases", headers=member, json={"secret_id": "broker"}).status_code == 424
    monkeypatch.setenv("MO_HTTP_SECRET", "top-secret-value-xyz")
    r = c.post(A + "/vault/leases", headers=member, json={"secret_id": "broker", "ttl_seconds": 60})
    assert r.status_code == 201 and "top-secret-value-xyz" not in r.text
    lid = r.json()["data"]["lease_id"]
    assert c.delete(f"{A}/vault/leases/{lid}", headers=member).status_code == 200
    assert c.delete(f"{A}/vault/leases/{lid}", headers=member).status_code == 404
    assert c.post(A + "/vault/leases", headers=member, json={"secret_id": "unknown"}).status_code == 404
