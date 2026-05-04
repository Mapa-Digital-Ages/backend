"""Login service for user authentication."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from md_backend.models.db_models import (
    GuardianStatusEnum,
    UserProfile,
)
from md_backend.utils.security import create_access_token, verify_password


def _derive_role(user: UserProfile) -> str:
    if user.admin_profile is not None:
        return "admin"
    if user.student_profile is not None:
        return "student"
    return "guardian"


class LoginService:
    """Service for handling user login."""

    async def login(self, email: str, password: str, session: AsyncSession) -> dict:
        """Authenticate user and return JWT token, or error dict."""
        result = await session.execute(
            select(UserProfile)
            .options(
                selectinload(UserProfile.guardian_profile),
                selectinload(UserProfile.admin_profile),
                selectinload(UserProfile.student_profile),
            )
            .where(UserProfile.email == email)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return {"error": "invalid_credentials"}

        if not verify_password(password, user.password):
            return {"error": "invalid_credentials"}
        
        if not user.is_active:
            return {"error": "invalid_credentials"}

        if user.guardian_profile is not None:
            if user.guardian_profile.guardian_status == GuardianStatusEnum.WAITING:
                return {"error": "WAITING"}
            if user.guardian_profile.guardian_status == GuardianStatusEnum.REJECTED:
                return {"error": "REJECTED"}

        token = create_access_token({"sub": user.email, "user_id": str(user.id)})
        name = f"{user.first_name} {user.last_name}".strip()
        return {
            "token": token,
            "role": _derive_role(user),
            "email": user.email,
            "name": name,
        }
