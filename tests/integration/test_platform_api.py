"""
The platform API, driven through the live app with real JWTs.
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


P = "/api/mo/platform"

ROUTES = [
    ("get", "/knowledge/docs"), ("post", "/knowledge/docs"), ("post", "/knowledge/search"),
    ("post", "/knowledge/answer"), ("post", "/memory"), ("post", "/memory/recall"),
    ("get", "/memory/stats"), ("post", "/runs"), ("get", "/runs"), ("get", "/runs/x"),
    ("get", "/autonomy"), ("put", "/autonomy"), ("post", "/control/dry-run"),
    ("get", "/protocols/peers"), ("post", "/protocols/mcp"), ("get", "/protocols/a2a/card"),
    ("post", "/protocols/a2a/inbound"), ("get", "/domain/tools"), ("post", "/domain/forecast"),
    ("get", "/evals/suites"), ("post", "/evals/run"), ("get", "/observability/metrics"),
    ("get", "/observability/traces"), ("get", "/manifest"),
]


@pytest.mark.parametrize("method,path", ROUTES)
def test_every_platform_route_requires_authentication(app_and_client, method, path):
    _, client, _ = app_and_client
    kwargs = {} if method == "get" else {"json": {}}
    assert getattr(client, method)(P + path, **kwargs).status_code == 401


# ── knowledge ────────────────────────────────────────────────────────────────

def test_knowledge_ingest_search_answer_and_refusal(app_and_client, auth):
    _, c, _ = app_and_client
    r = c.post(P + "/knowledge/docs", headers=auth, json={
        "title": "Refunds", "text": "Customers may request a refund within 30 days of purchase. "
                                    "Refunds are issued to the original payment method."})
    assert r.status_code == 201, r.text
    doc_id = r.json()["data"]["doc_id"] if "doc_id" in r.json()["data"] else r.json()["data"]["id"]
    hits = c.post(P + "/knowledge/search", headers=auth, json={"query": "refund window days"}).json()["results"]
    assert hits and "Refunds" in str(hits[0])
    ans = c.post(P + "/knowledge/answer", headers=auth, json={"question": "How long do I have to request a refund?"})
    assert ans.status_code in (200, 424), ans.text        # 424 = no model provider configured, stated honestly
    off = c.post(P + "/knowledge/answer", headers=auth, json={"question": "zebra quantum submarine recipe"})
    assert off.status_code != 200 or off.json()["data"].get("grounded") is not True
    assert c.delete(f"{P}/knowledge/docs/{doc_id}", headers=auth).status_code == 200
    assert c.delete(f"{P}/knowledge/docs/{doc_id}", headers=auth).status_code == 404


def test_knowledge_is_tenant_isolated(app_and_client, auth, other):
    _, c, _ = app_and_client
    c.post(P + "/knowledge/docs", headers=auth, json={"title": "Secret plan", "text": "Project Aurora launches in March."})
    assert c.post(P + "/knowledge/search", headers=other, json={"query": "Aurora launches"}).json()["results"] == []
    docs_b = c.get(P + "/knowledge/docs", headers=other).json()["documents"]
    assert all("Aurora" not in str(d) for d in docs_b)


def test_secret_in_document_is_not_ingested_silently(app_and_client, auth):
    _, c, _ = app_and_client
    r = c.post(P + "/knowledge/docs", headers=auth, json={"title": "keys", "text": "aws key " + FAKE_AWS_KEY + " here"})
    listed = c.get(P + "/knowledge/docs", headers=auth).text
    assert FAKE_AWS_KEY not in listed and FAKE_AWS_KEY not in r.text


def test_input_limits(app_and_client, auth):
    _, c, _ = app_and_client
    assert c.post(P + "/knowledge/docs", headers=auth, json={"title": "", "text": "x"}).status_code == 422
    assert c.post(P + "/memory/recall", headers=auth, json={"query": "q", "top_k": 999}).status_code == 422


# ── memory ───────────────────────────────────────────────────────────────────

def test_memory_roundtrip_private_by_default_and_erase(app_and_client, auth, member):
    _, c, _ = app_and_client
    r = c.post(P + "/memory", headers=auth, json={"kind": "LONG_TERM", "content": "Prefers dark mode dashboards"})
    assert r.status_code == 201, r.text
    got = c.post(P + "/memory/recall", headers=auth, json={"query": "dark mode"}).json()["memories"]
    assert got
    # a different actor in the same tenant cannot see a private memory
    assert c.post(P + "/memory/recall", headers=member, json={"query": "dark mode"}).json()["memories"] == []
    assert c.get(P + "/memory/stats", headers=auth).status_code == 200
    assert c.post(P + "/memory/erase", headers=auth, json={}).status_code == 409
    assert c.post(P + "/memory/erase", headers=auth, json={"confirm": True}).status_code == 200
    assert c.post(P + "/memory/recall", headers=auth, json={"query": "dark mode"}).json()["memories"] == []


def test_memory_refuses_secrets(app_and_client, auth):
    _, c, _ = app_and_client
    r = c.post(P + "/memory", headers=auth, json={"kind": "WORKING", "content": "password is hunter2 and key " + FAKE_AWS_KEY})
    assert r.status_code >= 400 or FAKE_AWS_KEY not in str(
        c.post(P + "/memory/recall", headers=auth, json={"query": "password key"}).json())


# ── runs ─────────────────────────────────────────────────────────────────────

PLAN = {"name": "quick-forecast", "steps": [
    {"key": "f", "kind": "tool", "target": "domain.forecast", "input": {"series": [1, 2, 3, 4, 5, 6], "horizon": 2}}]}


def _allow_forecast(c, auth):
    r = c.put(P + "/autonomy", headers=auth, json={"subject": "domain.forecast", "level": 2, "reason": "test"})
    assert r.status_code == 200, r.text


def test_default_autonomy_parks_step_for_approval(app_and_client, auth):
    _, c, _ = app_and_client
    rid = c.post(P + "/runs", headers=auth, json=PLAN).json()["data"]["run_id"]
    ex = c.post(f"{P}/runs/{rid}/execute", headers=auth, json={})
    assert ex.status_code == 202, ex.text
    assert ex.json()["state"] == "PENDING_APPROVAL"
    assert c.get(f"{P}/runs/{rid}", headers=auth).json()["status"] == "AWAITING_APPROVAL"


def test_run_lifecycle_and_tenant_isolation(app_and_client, auth, other):
    _, c, _ = app_and_client
    _allow_forecast(c, auth)
    r = c.post(P + "/runs", headers=auth, json=PLAN)
    assert r.status_code == 201, r.text
    rid = r.json()["data"]["run_id"]
    ex = c.post(f"{P}/runs/{rid}/execute", headers=auth, json={})
    assert ex.status_code == 200, ex.text
    desc = c.get(f"{P}/runs/{rid}", headers=auth).json()
    assert desc["status"] == "SUCCEEDED"
    assert any(rid in (x.get("id"), x.get("run_id")) for x in c.get(P + "/runs", headers=auth).json()["runs"])
    assert c.get(f"{P}/runs/{rid}", headers=other).status_code == 404
    assert c.post(f"{P}/runs/{rid}/execute", headers=other, json={}).status_code == 404
    assert c.post(f"{P}/runs/{rid}/cancel", headers=other).status_code == 404


def test_invalid_plan_is_rejected(app_and_client, auth):
    _, c, _ = app_and_client
    assert c.post(P + "/runs", headers=auth, json={"name": "x", "steps": []}).status_code == 422


def test_finished_run_cannot_be_cancelled(app_and_client, auth):
    _, c, _ = app_and_client
    _allow_forecast(c, auth)
    rid = c.post(P + "/runs", headers=auth, json=PLAN).json()["data"]["run_id"]
    assert c.post(f"{P}/runs/{rid}/execute", headers=auth, json={}).status_code == 200
    assert c.post(f"{P}/runs/{rid}/cancel", headers=auth).status_code == 409


# ── autonomy ─────────────────────────────────────────────────────────────────

def test_autonomy_defaults_and_admin_only_changes(app_and_client, auth, member):
    _, c, _ = app_and_client
    body = c.get(P + "/autonomy", headers=auth).json()
    assert body["default_level"] == 1 and body["default_ceiling"] == 3
    assert c.put(P + "/autonomy", headers=member, json={"subject": "domain", "level": 3}).status_code == 403
    ok = c.put(P + "/autonomy", headers=auth, json={"subject": "domain", "level": 3, "reason": "trusted analytics"})
    assert ok.status_code == 200, ok.text
    over = c.put(P + "/autonomy", headers=auth, json={"subject": "domain", "level": 5})
    assert over.status_code == 403        # above the ceiling
    assert c.put(P + "/autonomy", headers=auth, json={"subject": "d", "level": 9}).status_code == 422


def test_promotion_without_evidence_is_refused(app_and_client, auth):
    _, c, _ = app_and_client
    r = c.post(P + "/autonomy/promote", headers=auth, json={"subject": "new.subject"})
    assert r.status_code == 409
    assert "Promotion refused" in r.json()["detail"]


def test_shadow_flow_records_decision_once(app_and_client, auth):
    _, c, _ = app_and_client
    sid = c.post(P + "/autonomy/shadow", headers=auth,
                 json={"subject": "s1", "action": "send", "proposal": {"to": "a"}}).json()["data"]["shadow_id"]
    assert c.post(f"{P}/autonomy/shadow/{sid}/decision", headers=auth, json={"human": {"to": "a"}}).status_code == 200
    assert c.post(f"{P}/autonomy/shadow/{sid}/decision", headers=auth, json={"human": {"to": "a"}}).status_code == 409
    assert c.get(P + "/autonomy/evidence", params={"subject": "s1"}, headers=auth).json()["samples"] == 1


# ── control ──────────────────────────────────────────────────────────────────

def test_dry_run_does_not_execute(app_and_client, auth):
    _, c, _ = app_and_client
    ok = c.post(P + "/control/dry-run", headers=auth, json={"tool": "domain.forecast", "payload": {"series": [1, 2, 3, 4], "horizon": 1}})
    assert ok.status_code == 200 and ok.json()["would_run"] is True
    unknown = c.post(P + "/control/dry-run", headers=auth, json={"tool": "no.such"}).json()
    assert unknown["would_run"] is False


def test_rollback_of_unknown_action_is_404(app_and_client, auth):
    _, c, _ = app_and_client
    assert c.post(P + "/control/rollback/nope", headers=auth).status_code == 404


# ── protocols ────────────────────────────────────────────────────────────────

def test_peer_management_is_admin_only_and_ssrf_guarded(app_and_client, auth, member):
    _, c, _ = app_and_client
    body = {"name": "evil", "protocol": "MCP", "url": "http://127.0.0.1:8080/mcp"}
    assert c.post(P + "/protocols/peers", headers=member, json=body).status_code == 403
    r = c.post(P + "/protocols/peers", headers=auth, json=body)
    assert r.status_code >= 400, "loopback peers must be refused"
    assert c.get(P + "/protocols/peers", headers=auth).json()["peers"] == []


def test_mcp_server_speaks_jsonrpc_and_hides_peer_tools(app_and_client, auth):
    _, c, _ = app_and_client
    init = c.post(P + "/protocols/mcp", headers=auth, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init.status_code == 200 and init.json()["result"]["serverInfo"]
    tools = c.post(P + "/protocols/mcp", headers=auth, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()
    names = [t["name"] for t in tools["result"]["tools"]]
    assert any(n.startswith("domain.") for n in names)
    assert not any(n.startswith("mcp.") for n in names)
    note = c.post(P + "/protocols/mcp", headers=auth, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note.status_code == 202


def test_a2a_card_and_unknown_peer_inbound_is_refused(app_and_client, auth):
    _, c, _ = app_and_client
    assert c.get(P + "/protocols/a2a/card", headers=auth).status_code == 200
    r = c.post(P + "/protocols/a2a/inbound", headers=auth, json={"peer": "ghost", "timestamp": 1, "nonce": "n", "task": {}, "signature": "s"})
    assert r.status_code == 403
    assert c.post(P + "/protocols/a2a/inbound", headers=auth, json={"junk": 1}).status_code == 422


def test_a2a_send_to_unknown_peer(app_and_client, auth):
    _, c, _ = app_and_client
    r = c.post(P + "/protocols/a2a/send", headers=auth, json={"peer": "ghost", "tool": "x"})
    assert r.status_code == 404


# ── domain intelligence ──────────────────────────────────────────────────────

def test_domain_tools_listed_and_run(app_and_client, auth):
    _, c, _ = app_and_client
    names = [t["name"] for t in c.get(P + "/domain/tools", headers=auth).json()["tools"]]
    assert "domain.forecast" in names and "domain.finance" in names
    r = c.post(P + "/domain/forecast", headers=auth, json={"series": [10, 12, 14, 16, 18, 20], "horizon": 2})
    assert r.status_code == 200, r.text
    assert round(r.json()["data"]["forecast"][0]) == 22


def test_domain_rejects_bad_input_and_unknown_tool(app_and_client, auth):
    _, c, _ = app_and_client
    assert c.post(P + "/domain/forecast", headers=auth, json={"series": "nope"}).status_code >= 400
    assert c.post(P + "/domain/does_not_exist", headers=auth, json={}).status_code == 404


def test_domain_endpoint_cannot_reach_non_domain_tools(app_and_client, auth):
    _, c, _ = app_and_client
    assert c.post(P + "/domain/../voice", headers=auth, json={}).status_code == 404


# ── evaluation ───────────────────────────────────────────────────────────────

def test_eval_suites_run_persist_and_isolate(app_and_client, auth, other):
    _, c, _ = app_and_client
    names = [s["name"] for s in c.get(P + "/evals/suites", headers=auth).json()["suites"]]
    assert {"domain-engines", "guards", "governance"} <= set(names)
    r = c.post(P + "/evals/run", headers=auth, json={"suite": "guards"})
    assert r.status_code == 200, r.text
    rid = r.json()["data"]["run_id"]
    assert c.get(f"{P}/evals/runs/{rid}", headers=auth).json()["passed"] is True
    assert any(x["run_id"] == rid for x in c.get(P + "/evals/runs", headers=auth).json()["runs"])
    assert c.get(f"{P}/evals/runs/{rid}", headers=other).status_code == 404
    assert c.get(P + "/evals/runs", headers=other).json()["runs"] == []
    assert c.post(P + "/evals/run", headers=auth, json={"suite": "nope"}).status_code == 404


# ── observability and manifest ───────────────────────────────────────────────

def test_metrics_are_admin_only_and_prometheus_formatted(app_and_client, auth, member):
    _, c, _ = app_and_client
    assert c.get(P + "/observability/metrics", headers=member).status_code == 403
    c.post(P + "/domain/forecast", headers=auth, json={"series": [1, 2, 3, 4, 5, 6], "horizon": 2})
    r = c.get(P + "/observability/metrics", headers=auth)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "# TYPE" in r.text


def test_traces_are_tenant_scoped(app_and_client, auth, other):
    _, c, _ = app_and_client
    c.post(P + "/domain/forecast", headers=auth, json={"series": [1, 2, 3, 4], "horizon": 1})
    mine = c.get(P + "/observability/traces", headers=auth).json()["spans"]
    theirs = c.get(P + "/observability/traces", headers=other).json()["spans"]
    assert mine and not any(s in theirs for s in mine)
    assert c.get(P + "/observability/traces", params={"tree": True}, headers=auth).status_code == 422


def test_manifest_is_served_and_honest(app_and_client, auth):
    _, c, _ = app_and_client
    m = c.get(P + "/manifest", headers=auth).json()
    assert sum(m["summary"].values()) == len(m["capabilities"])
    assert m["summary"]["planned"] > 0 and m["known_blockers"]
    assert m["live"]["wake_word_mode"] == "transcript-keyword"
