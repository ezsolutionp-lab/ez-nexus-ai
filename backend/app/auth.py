"""
EZ-NEXUS AI — Authentication Module
JWT-based auth with bcrypt password hashing.
Seeds a default admin account on first startup.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import bcrypt as _bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from . import models, schemas
from .config import settings
from .database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


# ── Password helpers — using bcrypt directly (passlib has Python 3.14 issues) ─

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


# ── JWT helpers ───────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None


# ── Dependency: get current user (optional — returns None if no token) ────────

def get_optional_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Optional[models.User]:
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    email = payload.get("sub")
    if not email:
        return None
    return db.query(models.User).filter(models.User.email == email).first()


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    user = get_optional_user(token, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_admin_user(current_user: models.User = Depends(get_current_user)) -> models.User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return current_user


# ── Seed default admin on startup ─────────────────────────────────────────────

def seed_admin(db: Session):
    """Creates the default admin account if it doesn't exist."""
    existing = db.query(models.User).filter(
        models.User.email == settings.default_admin_email
    ).first()
    if not existing:
        admin = models.User(
            email=settings.default_admin_email,
            full_name="EZ-NEXUS Admin",
            hashed_password=hash_password(settings.default_admin_password),
            is_admin=True,
            is_active=True,
            plan="enterprise",
        )
        db.add(admin)
        db.commit()
        logger.info("Default admin account created: %s", settings.default_admin_email)
    else:
        logger.info("Admin account already exists: %s", settings.default_admin_email)


# ── Auth Routes ───────────────────────────────────────────────────────────────

@router.post("/register", response_model=schemas.UserOut, status_code=201)
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already registered.")
    user = models.User(
        email=payload.email,
        full_name=payload.full_name or payload.email.split("@")[0],
        hashed_password=hash_password(payload.password),
        is_admin=False,
        is_active=True,
        plan="starter",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("New user registered: %s", user.email)
    return user


@router.post("/login", response_model=schemas.TokenOut)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated.")

    user.last_login = datetime.utcnow()
    db.commit()

    token = create_access_token({"sub": user.email, "is_admin": user.is_admin})
    return schemas.TokenOut(
        access_token=token,
        token_type="bearer",
        user=schemas.UserOut.model_validate(user),
    )


@router.get("/me", response_model=schemas.UserOut)
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=schemas.UserOut)
def update_me(
    payload: schemas.UserUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.put("/me/password")
def change_password(
    payload: schemas.PasswordChange,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    current_user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return {"detail": "Password updated successfully."}


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(
    admin: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return db.query(models.User).all()
