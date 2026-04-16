"""Login service for user authentication."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import User, UserStatus
from md_backend.utils.security import create_access_token, verify_password


class LoginService:
    """Service for handling user login."""

    async def login(self, email: str, password: str, session: AsyncSession) -> dict:
        """Authenticate user and return JWT token, or error dict."""
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user is None:
            return {"error": "invalid_credentials"}

        if not verify_password(password, user.hashed_password):
            return {"error": "invalid_credentials"}

        if user.status == UserStatus.AGUARDANDO:
            return {"error": "AGUARDANDO"}

        if user.status == UserStatus.NEGADO:
            return {"error": "NEGADO"}

        token = create_access_token({"sub": user.email, "user_id": user.id})
        return {
            "token": token,
            "role": user.role,
            "email": user.email,
            "name": user.name,
        }
