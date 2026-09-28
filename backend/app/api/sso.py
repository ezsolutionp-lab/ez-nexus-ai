"""POST /auth/sso — exchange a verified OpenID Connect ID token for an MO access token."""

from __future__ import annotations

import secrets
from datetime import datetime

import bcrypt as _bcrypt
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import create_access_token
from ..database import get_db
from ..mo.errors import HTTP_STATUS_FOR_STATE
from ..mo.security import oidc

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/sso", response_model=schemas.TokenOut)
def sso_login(payload: dict = Body(...), db: Session = Depends(get_db)):
    res = oidc.verify_id_token(str(payload.get("id_token", "")))
    if not res.state.is_success:
        raise HTTPException(status_code=HTTP_STATUS_FOR_STATE.get(res.state, 401), detail=res.detail)
    info = res.data
    user = db.query(models.User).filter(models.User.email == info["email"]).first()
    if user is None:
        if not info["auto_provision"]:
            raise HTTPException(status_code=403, detail="No MO account exists for this identity, and auto-provisioning is off.")
        # SSO accounts get an unusable random password: they can only sign in through the identity provider.
        user = models.User(email=info["email"], full_name=info["name"] or info["email"].split("@")[0],
                           hashed_password=_bcrypt.hashpw(secrets.token_urlsafe(32).encode(), _bcrypt.gensalt()).decode(),
                           is_admin=info["is_admin"], is_active=True, plan="starter",
                           tenant_id=info["tenant_id"] or "tnt-default")
        db.add(user)
    elif info["is_admin"] and not user.is_admin:
        user.is_admin = True                              # promoted only by a configured admin group
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated.")
    user.last_login = datetime.utcnow()
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": user.email, "is_admin": user.is_admin})
    return schemas.TokenOut(access_token=token, token_type="bearer", user=schemas.UserOut.model_validate(user))
