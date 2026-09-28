"""
The conversational voice API, driven through the live app with real JWTs.

Covers authentication, session ownership and tenancy, input limits, and that a
full spoken conversation behaves the same over HTTP as it does in-process.
"""

import warnings

import pytest

warnings.filterwarnings("ignore")

pytestmark = pytest.mark.voice


@pytest.fixture(scope="module")
def app_and_client(tmp_path_factory):
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2] / "backend"
    db_path = tmp_path_factory.mktemp("voicedb") / "voice.db"
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
    return _token(app_and_client[2], "voice-admin@example.com", "tnt-voice-a", admin=True)


@pytest.fixture(scope="module")
def other_user(app_and_client):
    return _token(app_and_client[2], "voice-other@example.com", "tnt-voice-b", admin=True)


def _start(client, headers) -> str:
    resp = client.post("/api/mo/voice/sessions", json={}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["session_id"]


def _say(client, headers, sid, text):
    resp = client.post(f"/api/mo/voice/sessions/{sid}/turns",
                       json={"transcript": text}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── authentication ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path", [
    ("get", "/api/mo/voice/capabilities"),
    ("get", "/api/mo/voice/commands"),
    ("post", "/api/mo/voice/sessions"),
    ("post", "/api/mo/voice/sessions/x/turns"),
    ("get", "/api/mo/voice/sessions/x"),
    ("post", "/api/mo/voice/sessions/x/end"),
])
def test_every_voice_route_requires_authentication(app_and_client, method, path):
    _, client, _ = app_and_client
    kwargs = {"json": {"transcript": "hi"}} if method == "post" else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401


# ── capability honesty ───────────────────────────────────────────────────────

def test_capabilities_are_reported_truthfully(app_and_client, auth):
    _, client, _ = app_and_client
    body = client.get("/api/mo/voice/capabilities", headers=auth).json()
    text = str(body).lower()
    assert "transcript_keyword" in text or "keyword" in text
    assert "speaker" in text  # speaker verification gap is stated, not hidden


def test_commands_list_wake_phrases_and_examples(app_and_client, auth):
    _, client, _ = app_and_client
    body = client.get("/api/mo/voice/commands", headers=auth).json()
    assert "mo" in [p.lower() for p in body["wake_phrases"]]
    assert body["follow_up_window_seconds"] > 0
    assert body["examples"]


# ── conversation flow ────────────────────────────────────────────────────────

def test_ambient_speech_is_ignored_until_mo_is_called(app_and_client, auth):
    _, client, _ = app_and_client
    sid = _start(client, auth)
    reply = _say(client, auth, sid, "what should we have for dinner tonight")
    assert reply["awake"] is False
    assert not reply["reply"]


def test_calling_mo_wakes_it_and_it_answers(app_and_client, auth):
    _, client, _ = app_and_client
    sid = _start(client, auth)
    reply = _say(client, auth, sid, "MO")
    assert reply["awake"] is True
    assert reply["reply"]
    assert reply["speak"]  # a text-to-speech directive for the browser


def test_spoken_build_command_runs_a_real_build_over_http(app_and_client, auth):
    _, client, _ = app_and_client
    sid = _start(client, auth)
    _say(client, auth, sid, "hey MO")
    reply = _say(client, auth, sid, "build me a website for a plumbing company with online booking")
    assert reply["intent"]["intent"] == "builder.create_project"
    assert reply["ok"] is True
    assert "plumbing" in reply["reply"].lower()
    transcript = client.get(f"/api/mo/voice/sessions/{sid}", headers=auth).json()
    assert transcript["turn_count"] >= 2
    assert any(t["intent"] == "builder.create_project" for t in transcript["turns"])


def test_approval_cannot_be_granted_by_voice(app_and_client, auth):
    _, client, _ = app_and_client
    sid = _start(client, auth)
    _say(client, auth, sid, "MO")
    reply = _say(client, auth, sid, "approve the deployment")
    assert reply["ok"] is False
    assert "by voice" in reply["reply"].lower()


def test_never_mind_puts_mo_back_to_sleep(app_and_client, auth):
    _, client, _ = app_and_client
    sid = _start(client, auth)
    _say(client, auth, sid, "MO")
    reply = _say(client, auth, sid, "never mind")
    assert reply["awake"] is False


# ── ownership, tenancy, limits ───────────────────────────────────────────────

def test_another_tenant_cannot_read_or_use_a_session(app_and_client, auth, other_user):
    _, client, _ = app_and_client
    sid = _start(client, auth)
    _say(client, auth, sid, "MO")
    assert client.get(f"/api/mo/voice/sessions/{sid}", headers=other_user).status_code == 404
    resp = client.post(f"/api/mo/voice/sessions/{sid}/turns",
                       json={"transcript": "MO status"}, headers=other_user)
    assert resp.status_code in (403, 404)
    assert client.post(f"/api/mo/voice/sessions/{sid}/end", headers=other_user).status_code in (403, 404)


def test_oversize_transcript_is_rejected(app_and_client, auth):
    _, client, _ = app_and_client
    sid = _start(client, auth)
    resp = client.post(f"/api/mo/voice/sessions/{sid}/turns",
                       json={"transcript": "a" * 2001}, headers=auth)
    assert resp.status_code == 413


def test_non_string_transcript_is_rejected(app_and_client, auth):
    _, client, _ = app_and_client
    sid = _start(client, auth)
    resp = client.post(f"/api/mo/voice/sessions/{sid}/turns",
                       json={"transcript": 42}, headers=auth)
    assert resp.status_code == 422


def test_ending_a_session_stops_further_turns(app_and_client, auth):
    _, client, _ = app_and_client
    sid = _start(client, auth)
    _say(client, auth, sid, "MO")
    ended = client.post(f"/api/mo/voice/sessions/{sid}/end", headers=auth).json()
    assert ended["status"] != "ACTIVE"
    resp = client.post(f"/api/mo/voice/sessions/{sid}/turns",
                       json={"transcript": "MO"}, headers=auth)
    assert resp.status_code >= 400


def test_unknown_session_is_not_found(app_and_client, auth):
    _, client, _ = app_and_client
    assert client.get("/api/mo/voice/sessions/does-not-exist", headers=auth).status_code == 404


def test_a_long_conversation_is_not_throttled_but_builds_are(app_and_client, auth, monkeypatch):
    """Chatter must not hit the strict build ceiling; only sandboxed builds do."""
    from app.mo.security import zero_trust

    _, client, _ = app_and_client
    monkeypatch.setitem(zero_trust.RATE_LIMITS, "build", 1)
    zero_trust.limiter._hits.clear()
    sid = _start(client, auth)
    _say(client, auth, sid, "MO")
    for _ in range(20):                       # far above the 12/min build ceiling
        assert client.post(f"/api/mo/voice/sessions/{sid}/turns",
                           json={"transcript": "help"}, headers=auth).status_code == 200
    first = _say(client, auth, sid, "build me a booking website for a barber shop")
    second = _say(client, auth, sid, "build me a booking website for a bakery")
    assert first["ok"] is True
    assert second["state"] == "RATE_LIMITED"
