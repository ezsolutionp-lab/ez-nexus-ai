"""
Shared fixtures for the MO NEXUS OMEGA test suite.

Every test gets a fresh database built by the real Alembic migration chain, not
by `create_all` — so a broken migration fails the suite instead of hiding behind
metadata.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

# Provider keys must not leak into tests: the suite asserts credential-required
# behaviour and would silently pass differently on a developer machine.
for _var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SMTP_PASSWORD",
             "TWILIO_AUTH_TOKEN", "PAYMENTS_API_KEY"):
    os.environ.pop(_var, None)
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use-only")


@pytest.fixture(scope="session")
def migrated_db_url(tmp_path_factory) -> str:
    """A database created by running every migration forward."""
    db_path = tmp_path_factory.mktemp("db") / "mo_test.db"
    url = f"sqlite:///{db_path}"
    env = {**os.environ, "DATABASE_URL": url}
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND), env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"alembic upgrade failed:\n{proc.stdout}\n{proc.stderr}"
    return url


@pytest.fixture
def engine(migrated_db_url):
    from sqlalchemy import create_engine
    return create_engine(migrated_db_url, connect_args={"check_same_thread": False})


@pytest.fixture
def db(engine):
    """A session rolled back after each test, so tests never see each other's rows."""
    from sqlalchemy.orm import sessionmaker
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def tenant_a() -> str:
    return f"tnt-a-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def tenant_b() -> str:
    return f"tnt-b-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def ctx(tenant_a):
    from app.mo.context import RequestContext
    return RequestContext(
        tenant_id=tenant_a, actor_id="user-1", actor_label="alice",
        scopes=frozenset({"builder:read", "builder:write"}),
    )


@pytest.fixture
def admin_ctx(tenant_a):
    from app.mo.context import RequestContext
    return RequestContext(
        tenant_id=tenant_a, actor_id="admin-1", actor_label="root",
        is_admin=True, mfa_verified=True, scopes=frozenset({"*"}),
    )


@pytest.fixture
def other_admin_ctx(tenant_a):
    """A second approver — approvals require two distinct parties."""
    from app.mo.context import RequestContext
    return RequestContext(
        tenant_id=tenant_a, actor_id="admin-2", actor_label="second",
        is_admin=True, mfa_verified=True, scopes=frozenset({"*"}),
    )


@pytest.fixture
def workspace_root(tmp_path) -> Path:
    root = tmp_path / "workspaces"
    root.mkdir()
    return root


@pytest.fixture(autouse=True)
def _reset_singletons():
    from app.mo.tools.spec import reset_tool_registry
    from app.mo.modelfabric.router import reset_router
    from app.mo.events import fabric
    reset_tool_registry()
    reset_router()
    fabric.clear_subscribers()
    yield
    reset_tool_registry()
    reset_router()
    fabric.clear_subscribers()
