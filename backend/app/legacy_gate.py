"""
Authentication gate for the original EZ-NEXUS routes.

Before this, roughly 150 routes outside /api/mo (patients, invoices, CRM, ...) answered anyone. This
gate is an application-level dependency: every route needs a valid bearer token unless it is on the
short allow-list below, and routes that touch patient data need an administrator and are audited.

What this does NOT do: the legacy tables have no tenant column, so an authenticated user still sees
the shared legacy data. That needs a schema migration and is reported as a remaining limitation.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from starlette.requests import HTTPConnection
from sqlalchemy.orm import Session

from . import models
from .auth import decode_token
from .database import get_db

logger = logging.getLogger(__name__)

# (method, path regex). Everything else needs a token.
PUBLIC_ROUTES: tuple[tuple[str, re.Pattern], ...] = tuple((m, re.compile(p)) for m, p in (
    ("GET", r"^/$"),
    ("POST", r"^/auth/login$"),
    ("POST", r"^/auth/register$"),
    ("POST", r"^/auth/sso$"),                                # OIDC exchange: the ID token is the credential
    ("POST", r"^/marketing/forms/[^/]+/submit$"),          # public lead-capture form
    ("GET", r"^/appointments/approve/[^/]+$"),             # emailed one-time approval link
    ("POST", r"^/appointments/approve/[^/]+$"),
    ("GET", r"^/video/(download|stream)/[A-Za-z0-9_-]+$"),  # <video src> cannot send a bearer header
))
MO_PREFIX = "/api/mo"
TWILIO = re.compile(r"^/twilio/(inbound(/\d+)?|conversation/[^/]+)$")
PHI_PREFIXES = ("/patients", "/patient-intake", "/equipment-requests")


def _is_public(method: str, path: str) -> bool:
    return any(m == method and rx.match(path) for m, rx in PUBLIC_ROUTES)


async def _twilio_ok(request: Request) -> Optional[str]:
    """None when the webhook is authentic, else the reason it is refused."""
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    if not token:
        return "Twilio is not configured (TWILIO_AUTH_TOKEN missing); inbound webhooks are refused."
    sig = request.headers.get("X-Twilio-Signature", "")
    form = await request.form()
    from twilio.request_validator import RequestValidator
    url = os.getenv("TWILIO_WEBHOOK_BASE_URL", "").rstrip("/") + request.url.path if os.getenv("TWILIO_WEBHOOK_BASE_URL") \
        else str(request.url)
    return None if RequestValidator(token).validate(url, dict(form), sig) else "Twilio signature check failed."


async def legacy_gate(request: HTTPConnection, db: Session = Depends(get_db)) -> None:
    if request.scope.get("type") == "websocket":       # /ws checks its own ?token= before accepting
        return
    path, method = request.url.path, request.method.upper()
    if path.startswith(MO_PREFIX) or method == "OPTIONS" or path in ("/docs", "/redoc", "/openapi.json"):
        return
    if TWILIO.match(path):
        reason = await _twilio_ok(request)
        if reason:
            raise HTTPException(status.HTTP_403_FORBIDDEN, reason)
        return
    if _is_public(method, path):
        return

    header = request.headers.get("Authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ""
    payload = decode_token(token) if token else None
    user = db.query(models.User).filter(models.User.email == payload["sub"]).first() if payload and payload.get("sub") else None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.", headers={"WWW-Authenticate": "Bearer"})

    if any(path == p or path.startswith(p + "/") for p in PHI_PREFIXES):
        if not user.is_admin:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Patient data requires an administrator.")
        _audit_phi(db, user, method, path)


def _audit_phi(db: Session, user: models.User, method: str, path: str) -> None:
    """Record who touched patient data in the tamper-evident chain. A failure to audit must not expose data silently."""
    from .mo.audit import chain
    from .mo.context import RequestContext
    from .mo.errors import ResultState
    ctx = RequestContext(tenant_id=getattr(user, "tenant_id", None) or "default", actor_id=str(user.id),
                         actor_label=user.email, is_admin=True, scopes=frozenset({"*"}))
    chain.record(db, ctx, action="phi.access", result_state=ResultState.SUCCESS, resource_type="legacy_route",
                 resource_id=path[:120], detail=f"{method} {path}")
    db.commit()
