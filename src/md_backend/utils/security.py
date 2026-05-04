"""Security utilities for password hashing and JWT tokens."""

import datetime
import uuid

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from md_backend.models.db_models import (
    GuardianStatusEnum,
    UserProfile,
)
from md_backend.utils.database import get_db_session
from md_backend.utils.settings import settings

_bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(plain_password: str) -> str:
    """Hash a password with pepper and bcrypt."""
    peppered = (settings.PASSWORD_PEPPER + plain_password).encode("utf-8")
    return bcrypt.hashpw(peppered, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash (constant-time)."""
    peppered = (settings.PASSWORD_PEPPER + plain_password).encode("utf-8")
    return bcrypt.checkpw(peppered, hashed_password.encode("utf-8"))


def create_access_token(data: dict) -> str:
    """Create a JWT access token with expiration."""
    to_encode = data.copy()
    expire = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        minutes=settings.JWT_EXPIRATION_MINUTES
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT access token."""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """FastAPI dependency: extract and validate JWT from Authorization header."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    return payload


async def get_current_approved_user(
    payload: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """FastAPI dependency: verify user exists in DB and is approved."""
    result = await session.execute(
        select(UserProfile)
        .options(
            selectinload(UserProfile.guardian_profile),
            selectinload(UserProfile.admin_profile),
        )
        .where(UserProfile.id == uuid.UUID(payload["user_id"]))
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated",
        )

    if user.guardian_profile is not None:
        if user.guardian_profile.guardian_status == GuardianStatusEnum.WAITING:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account awaiting approval",
            )
        if user.guardian_profile.guardian_status == GuardianStatusEnum.REJECTED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account rejected",
            )

    is_superadmin = bool(user.admin_profile and user.admin_profile.is_superadmin)
    is_guardian = user.guardian_profile is not None

    return {
        "user_id": str(user.id),
        "email": user.email,
        "is_superadmin": is_superadmin,
        "is_guardian": is_guardian,
    }


async def get_current_superadmin(
    user: dict = Depends(get_current_approved_user),
) -> dict:
    """FastAPI dependency: verify user is a superadmin."""
    if not user["is_superadmin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted to administrators",
        )
    return user
