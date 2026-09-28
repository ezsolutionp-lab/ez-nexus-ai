"""
MO NEXUS OMEGA — Zero Trust HTTP surface.

Two rules make this enforceable rather than aspirational:

1. `mo_router()` returns an APIRouter whose *every* route already depends on an
   authenticated, tenant-resolved RequestContext. A new MO endpoint is protected
   because of how the router was constructed, not because the author remembered.
2. `PUBLIC_ROUTE_ALLOWLIST` is the only way a route becomes anonymous, and
   `audit_route_coverage()` walks the live app to prove no other route is open.
   That check runs in the test suite, so an unprotected route fails CI.

This module governs the `/api/mo/*` surface. The legacy EZ-NEXUS routes are
untouched here — closing those 155 anonymous endpoints is a separate migration
tracked as a production blocker, because changing them silently would break
existing clients.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from ...database import get_db
from ..context import RequestContext, SourceChannel
from ..errors import HTTP_STATUS_FOR_STATE, MoError, MoResult

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# Paths that may be reached without a token. Anything not listed is authenticated.
PUBLIC_ROUTE_ALLOWLIST: frozenset[str] = frozenset({
    "/api/mo/health",
    "/api/mo/openapi.json",
})

DEFAULT_TENANT_ID = "tnt-default"


# ── Rate limiting ────────────────────────────────────────────────────────────

class SlidingWindowLimiter:
    """Per-key sliding window. Backed by memory here; swap for Redis in multi-worker."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        now = time.monotonic()
        window = self._hits[key]
        while window and now - window[0] > window_seconds:
            window.popleft()
        if len(window) >= limit:
            return False, 0
        window.append(now)
        return True, limit - len(window)

    def reset(self, key: Optional[str] = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


limiter = SlidingWindowLimiter()

# Per-route-class ceilings. Auth is deliberately far stricter than reads.
RATE_LIMITS: dict[str, int] = {
    "auth": 10,        # per minute, per IP — brute-force ceiling
    "write": 60,
    "read": 240,
    "build": 12,       # sandbox work is expensive
}


def hit_bucket(bucket: str, key: str) -> bool:
    """Charge one hit to a named bucket outside a request dependency (e.g. per voice build)."""
    allowed, _ = limiter.hit(f"{bucket}:{key}", RATE_LIMITS.get(bucket, 60))
    return allowed


def rate_limit(bucket: str = "read") -> Callable:
    """Dependency factory applying a named rate-limit bucket."""

    def dependency(request: Request) -> None:
        limit = RATE_LIMITS.get(bucket, 60)
        client = request.client.host if request.client else "unknown"
        actor = request.headers.get("authorization", "")[-24:] or client
        allowed, remaining = limiter.hit(f"{bucket}:{actor}", limit)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit of {limit} requests/minute for '{bucket}' exceeded.",
                headers={"Retry-After": "60"},
            )
        request.state.rate_limit_remaining = remaining

    return dependency


# ── Identity resolution ──────────────────────────────────────────────────────

def _decode(token: str) -> Optional[dict[str, Any]]:
    from ...auth import decode_token
    return decode_token(token)


def resolve_context(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> RequestContext:
    """Authenticate, resolve the tenant, and build the request's authority."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = _decode(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from ... import models
    user = db.query(models.User).filter(models.User.email == payload["sub"]).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Account is inactive or no longer exists.")

    tenant_id = getattr(user, "tenant_id", None) or DEFAULT_TENANT_ID

    from ..db import Tenant
    tenant = db.get(Tenant, tenant_id)
    if tenant is not None and not tenant.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant is deactivated.")
    if tenant is not None and tenant.safe_mode and request.method not in ("GET", "HEAD", "OPTIONS"):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Tenant is in Safe Mode. Write operations are suspended.",
        )

    scopes = set(payload.get("scopes") or [])
    if user.is_admin:
        scopes.add("*")
    else:
        # A non-admin gets read/write on the builder surface; privileged scopes
        # (deploy, net, comms, payments) are granted explicitly, never by default.
        scopes.update({"builder:read", "builder:write"})

    return RequestContext(
        tenant_id=tenant_id,
        actor_id=str(user.id),
        actor_type="user",
        actor_label=user.email,
        is_admin=bool(user.is_admin),
        scopes=frozenset(scopes),
        source_channel=request.headers.get("x-mo-channel", SourceChannel.API),
        mfa_verified=bool(payload.get("mfa")),
        data_classification=request.headers.get("x-mo-data-class", "INTERNAL"),
        ip_address=request.client.host if request.client else None,
    )


def require_admin(ctx: RequestContext = Depends(resolve_context)) -> RequestContext:
    if not ctx.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required.")
    return ctx


def require_scope(scope: str) -> Callable:
    def dependency(ctx: RequestContext = Depends(resolve_context)) -> RequestContext:
        try:
            ctx.require_scope(scope)
        except MoError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail) from exc
        return ctx
    return dependency


# ── Router factory ───────────────────────────────────────────────────────────

def mo_router(prefix: str, tags: list[str], *, bucket: str = "read") -> APIRouter:
    """
    An APIRouter that is authenticated by construction.

    Every route added to it inherits `resolve_context` and a rate-limit bucket,
    so forgetting to add a dependency cannot produce an anonymous endpoint.
    """
    return APIRouter(
        prefix=prefix,
        tags=tags,
        dependencies=[Depends(resolve_context), Depends(rate_limit(bucket))],
        responses={
            401: {"description": "Authentication required"},
            403: {"description": "Policy denied"},
            429: {"description": "Rate limited"},
        },
    )


# ── Coverage audit ───────────────────────────────────────────────────────────

def audit_route_coverage(app, prefix: str = "/api/mo") -> dict[str, Any]:
    """
    Walk the live app and report any MO route reachable without authentication.

    Used by the security test suite: an unprotected MO route fails the build.
    """
    unprotected: list[str] = []
    protected: list[str] = []
    for route in _walk_routes(app.routes):
        path = getattr(route, "path", "")
        if not path.startswith(prefix):
            continue
        if path in PUBLIC_ROUTE_ALLOWLIST:
            continue
        deps = getattr(getattr(route, "dependant", None), "dependencies", []) or []
        names = {getattr(d.call, "__name__", "") for d in _flatten(deps)}
        if "resolve_context" in names or "require_admin" in names or "dependency" in names:
            protected.append(path)
        else:
            unprotected.append(f"{sorted(getattr(route, 'methods', []) or [])} {path}")
    return {
        "prefix": prefix,
        "protected": sorted(set(protected)),
        "unprotected": sorted(set(unprotected)),
        "public_allowlist": sorted(PUBLIC_ROUTE_ALLOWLIST),
        "fully_covered": not unprotected,
    }


def _walk_routes(routes) -> list:
    """
    Yield every route, including those nested inside included routers.

    FastAPI wraps `include_router` results in an internal router object, so a
    flat scan of `app.routes` silently misses every mounted route — which would
    make this auditor report full coverage over an empty set.
    """
    found = []
    for route in routes:
        found.append(route)
        sub = getattr(route, "routes", None)
        if sub is None:
            original = getattr(route, "original_router", None)
            sub = getattr(original, "routes", None) if original else None
        if sub:
            found.extend(_walk_routes(sub))
    return found


def _flatten(dependencies) -> list:
    out = []
    for dep in dependencies:
        out.append(dep)
        out.extend(_flatten(getattr(dep, "dependencies", []) or []))
    return out


def http_error_from(result: MoResult) -> HTTPException:
    """Map a non-success MoResult onto the HTTP status that is actually true."""
    return HTTPException(
        status_code=HTTP_STATUS_FOR_STATE.get(result.state, 400),
        detail={"state": result.state.value, "detail": result.detail, **({"meta": result.meta} if result.meta else {})},
    )


def raise_for(result: MoResult) -> MoResult:
    if not result.state.is_success:
        raise http_error_from(result)
    return result
