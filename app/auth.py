from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID
import os

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from app.database import get_db
from app import models, schemas

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────

SECRET_KEY   = os.getenv("SECRET_KEY", "fallback-secret-key")
ALGORITHM    = os.getenv("ALGORITHM", "HS256")
EXPIRE_DAYS  = int(os.getenv("ACCESS_TOKEN_EXPIRE_DAYS", "7"))

# ─── Password hashing ─────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ─── JWT ──────────────────────────────────────────────────────────────────────

bearer_scheme = HTTPBearer(auto_error=True)

def create_access_token(user_id: UUID, company_id: UUID, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=EXPIRE_DAYS)
    payload = {
        "sub":        str(user_id),
        "company_id": str(company_id),
        "role":       role,
        "exp":        expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> schemas.TokenData:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id:    str = payload.get("sub")
        company_id: str = payload.get("company_id")
        role:       str = payload.get("role")
        if not user_id or not company_id or not role:
            raise ValueError("Incomplete token payload")
        return schemas.TokenData(
            user_id=UUID(user_id),
            company_id=UUID(company_id),
            role=models.UserRole(role),
        )
    except (JWTError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ─── Dependencies ─────────────────────────────────────────────────────────────

def get_current_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> schemas.TokenData:
    return decode_token(credentials.credentials)


def get_current_user(
    token_data: schemas.TokenData = Depends(get_current_token),
    db: Session = Depends(get_db),
) -> models.User:
    user = (
        db.query(models.User)
        .filter(models.User.id == token_data.user_id, models.User.is_active == True)
        .first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )
    return user


def require_roles(*roles: models.UserRole):
    """Factory that returns a dependency enforcing at least one of the given roles."""
    def _check(current_user: models.User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user
    return _check


# Convenience role guards
require_admin_or_officer = require_roles(
    models.UserRole.safety_officer,
    models.UserRole.company_admin,
    models.UserRole.super_admin,
)
require_company_admin = require_roles(
    models.UserRole.company_admin,
    models.UserRole.super_admin,
)
require_super_admin = require_roles(models.UserRole.super_admin)
