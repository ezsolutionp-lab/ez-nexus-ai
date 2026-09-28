"""
The gate on the original EZ-NEXUS routes: no anonymous access except a short allow-list, patient data is
admin-only and audited, Twilio webhooks need a valid signature.
"""

import warnings

import pytest

FAKE_AWS_KEY = "AK" + "IA" + "ABCDEFGHIJKLMNOP"   # built at runtime so no credential-shaped literal is committed

warnings.filterwarnings("ignore")

pytestmark = pytest.mark.security


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



import re

from fastapi.routing import APIRoute

PUBLIC_EXAMPLES = [("get", "/"), ("post", "/auth/login")]


def _legacy_routes(app):
    for r in app.routes:
        if isinstance(r, APIRoute) and not r.path.startswith("/api/mo"):
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                yield m.lower(), re.sub(r"\{[^}]+\}", "1", r.path), r.path


def test_every_legacy_route_refuses_anonymous_callers(app_and_client):
    from app.legacy_gate import MO_PREFIX, TWILIO, _is_public
    app, c, _ = app_and_client
    checked, leaks = 0, []
    for method, url, template in _legacy_routes(app):
        if _is_public(method.upper(), url) or TWILIO.match(url):
            continue
        checked += 1
        resp = getattr(c, method)(url)
        if resp.status_code != 401:
            leaks.append((method, template, resp.status_code))
    assert checked >= 120, "the route walker stopped seeing the legacy routes"
    assert leaks == [], f"legacy routes reachable without a token: {leaks}"


def test_public_allow_list_is_small_and_explicit():
    from app.legacy_gate import PUBLIC_ROUTES
    assert len(PUBLIC_ROUTES) <= 8
    assert {p.pattern for _, p in PUBLIC_ROUTES} >= {r"^/$", r"^/auth/login$"}


def test_root_and_login_stay_reachable(app_and_client):
    _, c, _ = app_and_client
    assert c.get("/").status_code == 200
    assert c.post("/auth/login", data={"username": "nobody@example.com", "password": "wrong-password"}).status_code == 401


def test_bad_or_expired_token_is_rejected(app_and_client):
    _, c, _ = app_and_client
    assert c.get("/contacts", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    from datetime import timedelta
    from app.auth import create_access_token
    old = create_access_token({"sub": "plat-admin@example.com"}, timedelta(seconds=-5))
    assert c.get("/contacts", headers={"Authorization": f"Bearer {old}"}).status_code == 401


def test_authenticated_user_reaches_ordinary_legacy_routes(app_and_client, member):
    _, c, _ = app_and_client
    assert c.get("/contacts", headers=member).status_code == 200


def test_patient_data_is_admin_only_and_audited(app_and_client, auth, member):
    from app.mo.db import AuditEvent
    _, c, SessionLocal = app_and_client
    for path in ("/patients", "/patient-intake", "/equipment-requests"):
        assert c.get(path, headers=member).status_code == 403, path
        assert c.get(path).status_code == 401, path
    before = SessionLocal().query(AuditEvent).filter(AuditEvent.action == "phi.access").count()
    assert c.get("/patients", headers=auth).status_code == 200
    db = SessionLocal()
    after = db.query(AuditEvent).filter(AuditEvent.action == "phi.access").count()
    assert after == before + 1
    from app.mo.audit.chain import verify_chain
    tenants = {e.tenant_id for e in db.query(AuditEvent).filter(AuditEvent.action == "phi.access")}
    assert all(verify_chain(db, t)["valid"] for t in tenants)


def test_twilio_webhooks_need_a_valid_signature(app_and_client, monkeypatch):
    _, c, _ = app_and_client
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    assert c.post("/twilio/inbound", data={"CallSid": "CA1"}).status_code == 403          # not configured: refused, not open
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-twilio-token-value")
    assert c.post("/twilio/inbound", data={"CallSid": "CA1"}, headers={"X-Twilio-Signature": "forged"}).status_code == 403
    from twilio.request_validator import RequestValidator
    params = {"CallSid": "CA1", "From": "+15550100"}
    sig = RequestValidator("test-twilio-token-value").compute_signature("http://testserver/twilio/inbound", params)
    ok = c.post("/twilio/inbound", data=params, headers={"X-Twilio-Signature": sig})
    assert ok.status_code != 403 and ok.status_code != 401


def test_websocket_requires_a_token(app_and_client, member):
    from starlette.websockets import WebSocketDisconnect
    _, c, _ = app_and_client
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/ws/anon-1") as ws:
            ws.receive_text()
    token = member["Authorization"].split(" ", 1)[1]
    with c.websocket_connect(f"/ws/user-1?token={token}") as ws:
        ws.send_text("ping")


def test_no_default_password_is_committed():
    from app.config import Settings
    assert Settings.model_fields["default_admin_password"].default is None
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[2]
    hits = [str(p) for p in (src / "backend" / "app").rglob("*.py") if "Commander@2024" in p.read_text()]
    hits += [str(p) for p in (src / "frontend" / "src").rglob("*.jsx") if "Commander@2024" in p.read_text()]
    assert hits == []


def test_first_start_generates_a_strong_admin_password_in_a_private_file(tmp_path, monkeypatch):
    import os
    import stat
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app import auth, models
    from app.config import settings
    from app.database import Base
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    target = tmp_path / ".initial"
    monkeypatch.setattr(settings, "default_admin_password", None)
    monkeypatch.setattr(settings, "initial_admin_password_file", str(target))
    monkeypatch.setattr(settings, "default_admin_email", "seed-test@example.com")
    auth.seed_admin(db)
    password = target.read_text().strip()
    assert len(password) >= 20 and stat.S_IMODE(os.stat(target).st_mode) == 0o600
    user = db.query(models.User).filter_by(email="seed-test@example.com").one()
    assert auth.verify_password(password, user.hashed_password) and user.is_admin
