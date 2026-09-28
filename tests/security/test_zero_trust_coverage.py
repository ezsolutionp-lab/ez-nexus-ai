"""
Zero Trust coverage over the live application.

These tests walk the real FastAPI app. If anyone adds an MO route without
authentication, or the route-walker stops seeing nested routers, the build fails
here rather than in production.
"""

import pytest

pytestmark = pytest.mark.security


@pytest.fixture(scope="module")
def app():
    import warnings
    warnings.filterwarnings("ignore")
    from app.main import app as fastapi_app
    return fastapi_app


def test_route_walker_sees_nested_routers(app):
    """FastAPI nests included routers; a flat scan would report a false all-clear."""
    from app.mo.security.zero_trust import _walk_routes
    flat = [r for r in app.routes if getattr(r, "path", "").startswith("/api/mo")]
    walked = [r for r in _walk_routes(app.routes) if getattr(r, "path", "").startswith("/api/mo")]
    assert len(walked) > len(flat), "the walker is not descending into included routers"
    assert len(walked) >= 30


def test_no_mo_route_is_reachable_anonymously(app):
    from app.mo.security.zero_trust import audit_route_coverage
    report = audit_route_coverage(app)
    assert report["fully_covered"] is True, (
        f"These MO routes accept anonymous requests: {report['unprotected']}")
    assert len(report["protected"]) >= 25


def test_public_allowlist_stays_minimal(app):
    from app.mo.security.zero_trust import PUBLIC_ROUTE_ALLOWLIST
    assert PUBLIC_ROUTE_ALLOWLIST == frozenset({"/api/mo/health", "/api/mo/openapi.json"})


def test_anonymous_requests_to_mo_endpoints_return_401(app):
    from fastapi.testclient import TestClient
    client = TestClient(app)
    for path in ("/api/mo/status", "/api/mo/builder/projects", "/api/mo/builder/status",
                 "/api/mo/audit/verify", "/api/mo/approvals"):
        response = client.get(path)
        assert response.status_code == 401, f"{path} returned {response.status_code}, not 401"


def test_mo_health_is_the_one_open_route(app):
    from fastapi.testclient import TestClient
    client = TestClient(app)
    response = client.get("/api/mo/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_invalid_token_is_rejected(app):
    from fastapi.testclient import TestClient
    client = TestClient(app)
    response = client.get("/api/mo/status", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_builder_write_routes_carry_the_build_rate_limit_bucket(app):
    """Sandbox work is expensive; it must not sit on the permissive read bucket."""
    from app.api.builder import build_router
    from app.mo.security.zero_trust import RATE_LIMITS
    assert RATE_LIMITS["build"] < RATE_LIMITS["read"]
    assert RATE_LIMITS["auth"] <= 10
    assert len(build_router.dependencies) == 2
