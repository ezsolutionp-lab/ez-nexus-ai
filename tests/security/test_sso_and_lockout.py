"""OpenID Connect sign-in and password lockout."""

import json
import time
import warnings

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.mo.security import oidc

warnings.filterwarnings("ignore")
pytestmark = pytest.mark.security

ISSUER, AUD = "http://127.0.0.1:9", "mo-app"


def _keypair(kid="k1"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid=kid, alg="RS256", use="sig")
    return key, jwk


KEY, JWK = _keypair()


def _token(claims=None, key=KEY, kid="k1", alg="RS256", **over):
    body = {"iss": ISSUER, "aud": AUD, "sub": "u-1", "email": "sso.user@example.com", "email_verified": True,
            "name": "Sso User", "exp": int(time.time()) + 300, **(claims or {}), **over}
    return jwt.encode(body, key, algorithm=alg, headers={"kid": kid})


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setenv("MO_PROTOCOL_ALLOW_PRIVATE", "1")
    for k, v in (("MO_OIDC_ISSUER", ISSUER), ("MO_OIDC_AUDIENCE", AUD), ("MO_OIDC_ADMIN_GROUPS", "mo-admins")):
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("MO_OIDC_AUTO_PROVISION", raising=False)
    fetches = []
    oidc.reset_cache()

    def handler(request):
        fetches.append(1)
        return httpx.Response(200, json={"keys": [JWK]})
    monkeypatch.setattr(oidc, "transport", httpx.MockTransport(handler))
    yield fetches
    oidc.reset_cache()


def test_valid_token_is_accepted_and_claims_extracted():
    res = oidc.verify_id_token(_token({"groups": ["mo-admins"], "tenant_id": "tnt-x"}))
    assert res.state.is_success and res.data["email"] == "sso.user@example.com" and res.data["is_admin"] is True
    assert res.data["tenant_id"] == "tnt-x"


def test_non_admin_group_gives_no_admin_rights():
    assert oidc.verify_id_token(_token({"groups": ["staff"]})).data["is_admin"] is False
    assert oidc.verify_id_token(_token()).data["is_admin"] is False


@pytest.mark.parametrize("over,why", [
    ({"iss": "http://evil"}, "issuer"), ({"aud": "someone-else"}, "audience"),
    ({"exp": int(time.time()) - 600}, "expired"), ({"email_verified": False}, "unverified"),
    ({"email": ""}, "no email"),
])
def test_bad_claims_are_rejected(over, why):
    assert oidc.verify_id_token(_token(**over)).state.value == "POLICY_DENIED", why


def test_missing_required_claim_is_rejected():
    body = {"iss": ISSUER, "aud": AUD, "email": "a@example.com", "email_verified": True, "exp": int(time.time()) + 60}
    tok = jwt.encode(body, KEY, algorithm="RS256", headers={"kid": "k1"})          # no `sub`
    assert oidc.verify_id_token(tok).state.value == "POLICY_DENIED"


def test_token_signed_with_another_key_is_rejected():
    other, _ = _keypair("k1")
    assert oidc.verify_id_token(_token(key=other)).state.value == "POLICY_DENIED"


def test_unknown_kid_is_rejected_after_one_refetch(cfg):
    res = oidc.verify_id_token(_token(kid="nope"))
    assert res.state.value == "POLICY_DENIED" and "unknown key" in res.detail and len(cfg) == 2


def test_symmetric_algorithms_are_refused_to_stop_algorithm_confusion():
    public_pem = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(JWK))
    forged = jwt.encode({"iss": ISSUER, "aud": AUD, "sub": "x", "email": "a@example.com", "email_verified": True,
                         "exp": int(time.time()) + 60}, "shared-secret-key-0123456789abcdef", algorithm="HS256",
                        headers={"kid": "k1"})
    res = oidc.verify_id_token(forged)
    assert res.state.value == "POLICY_DENIED" and "not accepted" in res.detail
    none_tok = jwt.encode({"sub": "x"}, None, algorithm="none")
    assert oidc.verify_id_token(none_tok).state.value == "POLICY_DENIED"


def test_garbage_tokens_are_rejected():
    for bad in ("", "abc", "a.b", "a.b.c", "x" * 9000, None, 5):
        assert oidc.verify_id_token(bad).state.value == "POLICY_DENIED"


def test_keys_are_cached(cfg):
    oidc.verify_id_token(_token()); oidc.verify_id_token(_token())
    assert len(cfg) == 1


def test_unconfigured_sso_reports_credential_required(monkeypatch):
    monkeypatch.delenv("MO_OIDC_ISSUER")
    assert oidc.verify_id_token(_token()).state.value == "CREDENTIAL_REQUIRED"


def test_identity_provider_outage_is_reported(monkeypatch):
    monkeypatch.setattr(oidc, "transport", httpx.MockTransport(lambda r: httpx.Response(503)))
    oidc.reset_cache()
    assert oidc.verify_id_token(_token()).state.value == "PROVIDER_UNAVAILABLE"


def test_private_jwks_url_is_blocked_without_the_escape_hatch(monkeypatch):
    monkeypatch.delenv("MO_PROTOCOL_ALLOW_PRIVATE")
    oidc.reset_cache()
    assert oidc.verify_id_token(_token()).state.value == "PROVIDER_UNAVAILABLE"


# ── HTTP ─────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os
    import subprocess
    import sys
    from pathlib import Path
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    backend = Path(__file__).resolve().parents[2] / "backend"
    url = f"sqlite:///{tmp_path_factory.mktemp('sso') / 'sso.db'}"
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=str(backend),
                   env={**os.environ, "DATABASE_URL": url}, capture_output=True, text=True, check=True)
    os.environ["DATABASE_URL"] = url
    from app.database import get_db
    from app.main import app
    Session = sessionmaker(bind=create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool))

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override
    yield TestClient(app), Session
    app.dependency_overrides.clear()


def test_sso_endpoint_refuses_unknown_users_unless_auto_provision(client):
    c, _ = client
    r = c.post("/auth/sso", json={"id_token": _token()})
    assert r.status_code == 403 and "auto-provisioning is off" in r.json()["detail"]


def test_sso_endpoint_provisions_a_non_admin_and_issues_a_working_token(client, monkeypatch):
    c, Session = client
    monkeypatch.setenv("MO_OIDC_AUTO_PROVISION", "1")
    r = c.post("/auth/sso", json={"id_token": _token(email="new.hire@example.com", tenant_id="tnt-sso")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "new.hire@example.com" and body["user"]["is_admin"] is False
    me = c.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    from app import models
    assert Session().query(models.User).filter_by(email="new.hire@example.com").one().tenant_id == "tnt-sso"
    again = c.post("/auth/sso", json={"id_token": _token(email="new.hire@example.com")})
    assert again.status_code == 200


def test_admin_group_promotes_only_via_the_configured_group(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv("MO_OIDC_AUTO_PROVISION", "1")
    plain = c.post("/auth/sso", json={"id_token": _token(email="plain@example.com", groups=["staff"])}).json()
    boss = c.post("/auth/sso", json={"id_token": _token(email="boss@example.com", groups=["mo-admins"])}).json()
    assert plain["user"]["is_admin"] is False and boss["user"]["is_admin"] is True


def test_sso_endpoint_rejects_bad_tokens(client):
    c, _ = client
    assert c.post("/auth/sso", json={"id_token": "junk"}).status_code == 403
    assert c.post("/auth/sso", json={"id_token": _token(aud="other")}).status_code == 403


def test_sso_unconfigured_returns_424(client, monkeypatch):
    c, _ = client
    monkeypatch.delenv("MO_OIDC_ISSUER")
    assert c.post("/auth/sso", json={"id_token": _token()}).status_code == 424


# ── lockout ──────────────────────────────────────────────────────────────────

def test_repeated_wrong_passwords_lock_the_account(client):
    from app import models
    from app.auth import hash_password
    c, Session = client
    db = Session()
    db.add(models.User(email="lock.me@example.com", full_name="Lock", hashed_password=hash_password("correct-horse-battery"),
                       is_admin=False, is_active=True, plan="starter", tenant_id="tnt-lock"))
    db.commit()
    for _ in range(5):
        assert c.post("/auth/login", data={"username": "lock.me@example.com", "password": "wrong"}).status_code == 401
    locked = c.post("/auth/login", data={"username": "lock.me@example.com", "password": "correct-horse-battery"})
    assert locked.status_code == 429
    from datetime import datetime, timedelta
    u = Session().query(models.User).filter_by(email="lock.me@example.com").one()
    u.locked_until = datetime.utcnow() - timedelta(seconds=1)
    db2 = Session(); db2.merge(u); db2.commit()
    ok = c.post("/auth/login", data={"username": "lock.me@example.com", "password": "correct-horse-battery"})
    assert ok.status_code == 200
    assert Session().query(models.User).filter_by(email="lock.me@example.com").one().failed_login_count == 0
