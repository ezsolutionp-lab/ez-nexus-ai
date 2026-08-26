"""
Regression guard for pre-existing EZ-NEXUS / MO capabilities.

Instruction #1 §39: never silently remove a previously working MO capability.
These tests pin the legacy surface as it existed at commit 20069c7, so the MO
Builder work cannot quietly break it.
"""

import warnings

import pytest

warnings.filterwarnings("ignore")

pytestmark = pytest.mark.regression


@pytest.fixture(scope="module")
def app():
    from app.main import app as fastapi_app
    return fastapi_app


@pytest.fixture(scope="module")
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


# ── The app still boots and keeps every legacy route ─────────────────────────

def test_application_still_imports_and_boots(app):
    assert app.title == "EZ-NEXUS AI Platform"


def test_all_165_legacy_http_routes_are_still_mounted(app):
    from app.mo.security.zero_trust import _walk_routes
    legacy = [
        r for r in _walk_routes(app.routes)
        if getattr(r, "path", "").startswith("/") and hasattr(r, "methods")
        and not r.path.startswith("/api/mo")
        and r.path not in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc")
    ]
    assert len(legacy) >= 165, f"legacy route count dropped to {len(legacy)}"


def test_legacy_websocket_route_survives(app):
    paths = [getattr(r, "path", "") for r in app.routes]
    assert "/ws/{client_id}" in paths


def test_legacy_health_endpoint_unchanged(client):
    body = client.get("/").json()
    assert body["status"] == "ok"
    assert body["service"] == "EZ-NEXUS AI Platform"


# ── Existing modules still work ──────────────────────────────────────────────

def test_agent_registry_still_holds_21_agents():
    from app.agents import AGENT_REGISTRY
    assert len(AGENT_REGISTRY) == 21
    assert "appointment" in AGENT_REGISTRY
    assert "medical_data_entry" in AGENT_REGISTRY
    assert "recruitment" in AGENT_REGISTRY


def test_commander_agent_roster_intact():
    from app.commander import AGENT_ROSTER
    assert len(AGENT_ROSTER) == 13


def test_document_processor_still_extracts_text(tmp_path):
    from app.services.document_processor import DocumentProcessor
    csv = tmp_path / "intake.csv"
    csv.write_text("name,dob\nJane Doe,1980-01-01\n")
    text, confidence = DocumentProcessor().extract_text(str(csv))
    assert "Jane Doe" in text
    assert confidence > 0.9


def test_video_generator_entry_point_intact():
    from app.services.video_generator import generate_video_ad, _get_ffmpeg
    assert callable(generate_video_ad)
    assert _get_ffmpeg()


def test_twilio_twiml_helpers_intact():
    from app.twilio_voice import twiml_gather, twiml_say
    xml = twiml_gather("Hello", "/action")
    assert "<Gather" in xml and "Polly.Joanna" in xml
    assert "<Say" in twiml_say("Bye")


def test_auth_password_hashing_still_works():
    from app.auth import hash_password, verify_password
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


def test_ai_agent_heuristics_still_function():
    from app.ai_agent import analyze_transcript
    result = analyze_transcript(
        "Caller: My account is locked and I urgently need it reset immediately.")
    assert result["triage"] in ("urgent", "normal", "low")
    assert result["sentiment"] in ("positive", "neutral", "negative")


def test_legacy_orm_models_all_still_declared():
    from app import models
    for name in ("Business", "Appointment", "User", "Patient", "Invoice",
                 "EcomProduct", "Workflow", "AuditLog", "Lead", "Candidate"):
        assert hasattr(models, name), f"legacy model {name} disappeared"


# ── The new tenancy columns are additive, not breaking ───────────────────────

def test_user_model_gained_tenancy_without_losing_columns():
    from app import models
    columns = {c.name for c in models.User.__table__.columns}
    original = {"id", "email", "full_name", "hashed_password", "is_admin",
                "is_active", "plan", "created_at", "last_login"}
    assert original <= columns, "an original User column was removed"
    assert {"tenant_id", "mfa_enabled", "failed_login_count"} <= columns


def test_migration_chain_reaches_head_from_empty(tmp_path):
    """The whole chain applies cleanly to a fresh database."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2] / "backend"
    url = f"sqlite:///{tmp_path/'chain.db'}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(backend), env={**os.environ, "DATABASE_URL": url},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    import sqlite3
    tables = {r[0] for r in sqlite3.connect(tmp_path / "chain.db").execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "businesses" in tables and "appointments" in tables      # legacy
    assert "builder_projects" in tables and "mo_audit_events" in tables   # new
    assert len(tables) >= 67
