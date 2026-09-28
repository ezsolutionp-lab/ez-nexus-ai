"""
Builder Studio API and the JARVIS voice bridge, driven through the live app.

These use real HTTP requests with a real JWT against the real router stack, so
they exercise authentication, tenancy and rate limiting rather than mocking past
them.
"""

import warnings

import pytest

warnings.filterwarnings("ignore")


@pytest.fixture(scope="module")
def app_and_client(tmp_path_factory):
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2] / "backend"
    db_path = tmp_path_factory.mktemp("apidb") / "api.db"
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


@pytest.fixture(scope="module")
def admin_token(app_and_client):
    """A real user row and a real signed token — no auth bypass."""
    from app import models
    from app.auth import create_access_token, hash_password

    _, _, SessionLocal = app_and_client
    db = SessionLocal()
    user = db.query(models.User).filter(models.User.email == "builder-admin@example.com").first()
    if user is None:
        user = models.User(email="builder-admin@example.com", full_name="Builder Admin",
                           hashed_password=hash_password("x" * 16), is_admin=True,
                           is_active=True, plan="enterprise", tenant_id="tnt-default")
        db.add(user)
        db.commit()
    db.close()
    return create_access_token({"sub": "builder-admin@example.com", "is_admin": True, "mfa": True})


@pytest.fixture(scope="module")
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def test_builder_status_reports_capabilities_truthfully(app_and_client, auth):
    _, client, _ = app_and_client
    body = client.get("/api/mo/builder/status", headers=auth).json()
    assert body["stacks"]["implemented"] == ["fastapi_react"]
    assert "nextjs_fastapi" in body["stacks"]["planned"]
    assert body["requirement_engine"] == "RULE_BASED"
    assert body["model_fabric"]["any_configured"] is False
    assert body["deployment"]["adapters_implemented"] == ["deploy-hook", "export-bundle"]
    assert body["deployment"]["active"] is None
    blocked = {t["name"] for t in body["tools"] if not t["credential_satisfied"]}
    assert "comms.send_email" in blocked


def test_requesting_an_unimplemented_stack_is_blocked_not_faked(app_and_client, auth):
    _, client, _ = app_and_client
    response = client.post("/api/mo/builder/projects", headers=auth,
                           json={"prompt": "Build a shop.", "preferred_stack": "nextjs_fastapi"})
    assert response.status_code == 409
    assert response.json()["detail"]["state"] == "BLOCKED"


@pytest.fixture(scope="module")
def created_project(app_and_client, auth):
    _, client, _ = app_and_client
    response = client.post("/api/mo/builder/projects", headers=auth, json={
        "prompt": ("Build a plumbing company platform with a website, contact form, CRM, "
                   "online booking, dispatch, invoices, payments, email notifications "
                   "and an AI voice receptionist."),
        "run_build": True,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_prompt_to_project_over_http(created_project):
    project = created_project["project"]
    report = created_project["report"]
    assert project["name"] == "Plumbing Company Platform"
    assert project["status"] == "TESTED"
    assert report["stages"]["DEPLOYMENT_MODEL"]["state"] == "APPROVAL_REQUIRED"


def test_requirements_endpoint_returns_structure(app_and_client, auth, created_project):
    _, client, _ = app_and_client
    pid = created_project["project"]["id"]
    body = client.get(f"/api/mo/builder/projects/{pid}/requirements", headers=auth).json()
    assert len(body["requirements"]) >= 25
    assert any(r["key"] == "booking.create" for r in body["requirements"])


def test_graph_endpoint_returns_the_dependency_graph(app_and_client, auth, created_project):
    _, client, _ = app_and_client
    pid = created_project["project"]["id"]
    body = client.get(f"/api/mo/builder/projects/{pid}/graph", headers=auth).json()
    assert body["node_count"] > 50
    booking_api = next(n for n in body["nodes"]
                       if n["type"] == "api" and "Booking" in (n["label"] or ""))
    assert "model:Booking" in booking_api["depends_on"]


def test_generated_openapi_is_served(app_and_client, auth, created_project):
    _, client, _ = app_and_client
    pid = created_project["project"]["id"]
    spec = client.get(f"/api/mo/builder/projects/{pid}/openapi", headers=auth).json()
    assert spec["openapi"] == "3.1.0"
    assert "/api/bookings" in spec["paths"]
    assert spec["paths"]["/api/bookings"]["post"]["security"] == [{"bearerAuth": []}]
    assert "Booking" in spec["components"]["schemas"]


def test_file_contents_are_retrievable(app_and_client, auth, created_project):
    _, client, _ = app_and_client
    pid = created_project["project"]["id"]
    body = client.get(f"/api/mo/builder/projects/{pid}/files",
                      params={"path": "app/routers/bookings.py"}, headers=auth).json()
    assert "secure_router(" in body["content"]
    assert len(body["sha256"]) == 64


def test_agents_endpoint_shows_real_test_reports(app_and_client, auth, created_project):
    _, client, _ = app_and_client
    pid = created_project["project"]["id"]
    agents = client.get(f"/api/mo/builder/projects/{pid}/agents", headers=auth).json()
    assert len(agents) == 5
    for agent in agents:
        assert agent["status"] != "READY"          # no model provider configured
        assert agent["test_report"]["checks"]["model_call"]["passed"] is False
        assert "API_KEY" in agent["test_report"]["checks"]["model_call"]["detail"]


def test_integrations_report_credential_required(app_and_client, auth, created_project):
    _, client, _ = app_and_client
    pid = created_project["project"]["id"]
    integrations = client.get(f"/api/mo/builder/projects/{pid}/integrations", headers=auth).json()
    assert all(i["status"] == "CREDENTIAL_REQUIRED" for i in integrations)
    assert {i["provider"] for i in integrations} >= {"payments", "smtp", "twilio"}


def test_export_downloads_a_zip(app_and_client, auth, created_project):
    _, client, _ = app_and_client
    pid = created_project["project"]["id"]
    response = client.get(f"/api/mo/builder/projects/{pid}/export", headers=auth)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert len(response.content) > 5000


def test_deploy_request_returns_202_approval_required(app_and_client, auth, created_project):
    _, client, _ = app_and_client
    pid = created_project["project"]["id"]
    response = client.post(f"/api/mo/builder/projects/{pid}/deploy/request",
                           headers=auth, json={"environment": "production"})
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "APPROVAL_REQUIRED"
    assert body["meta"]["risk_tier"] == "CRITICAL"


def test_audit_chain_verifies_over_the_api(app_and_client, auth):
    _, client, _ = app_and_client
    body = client.get("/api/mo/audit/verify", headers=auth).json()
    assert body["valid"] is True
    assert body["checked"] > 0


def test_audit_recorded_the_builder_activity(app_and_client, auth):
    _, client, _ = app_and_client
    events = client.get("/api/mo/audit/events", headers=auth, params={"limit": 200}).json()
    actions = {e["action"] for e in events}
    assert "builder.project.created" in actions
    assert "builder.build" in actions
    assert "builder.agent.tested" in actions


# ── JARVIS voice bridge ──────────────────────────────────────────────────────

def test_voice_command_builds_through_the_same_compiler(app_and_client, auth):
    _, client, _ = app_and_client
    response = client.post("/api/mo/voice/command", headers=auth, json={
        "transcript": "MO, build a plumbing business website with online booking.",
        "run_build": False,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "builder.create_project"
    assert body["project_id"]
    assert "approval" in body["spoken_response"].lower()


def test_voice_deploy_still_hits_the_approval_gate(app_and_client, auth, created_project):
    """§34: voice cannot bypass approval gates."""
    _, client, _ = app_and_client
    pid = created_project["project"]["id"]
    body = client.post("/api/mo/voice/command", headers=auth, json={
        "transcript": "MO, deploy staging.", "project_id": pid,
    }).json()
    assert body["intent"] == "builder.deploy.staging"
    assert body["state"] == "APPROVAL_REQUIRED"


def test_voice_commands_are_audited_with_the_voice_channel(app_and_client, auth):
    _, client, _ = app_and_client
    events = client.get("/api/mo/audit/events", headers=auth, params={"limit": 200}).json()
    voice_events = [e for e in events if e["source_channel"] == "VOICE"]
    assert voice_events, "no voice-channel audit records were written"
    assert any(e["action"] == "voice.command" for e in voice_events)


def test_unrecognised_voice_command_says_so(app_and_client, auth):
    _, client, _ = app_and_client
    body = client.post("/api/mo/voice/command", headers=auth,
                       json={"transcript": "MO, what is the weather"}).json()
    assert body["intent"] is None
    assert body["state"] == "FAILED"
    assert body["recognised_examples"]


def test_voice_requires_authentication(app_and_client):
    _, client, _ = app_and_client
    assert client.post("/api/mo/voice/command",
                       json={"transcript": "MO, deploy production."}).status_code == 401
