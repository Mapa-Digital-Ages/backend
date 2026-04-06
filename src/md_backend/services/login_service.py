"""Login service for user authentication."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import User
from md_backend.utils.security import create_access_token, verify_password


class LoginService:
    """Service for handling user login."""

    async def login(self, email: str, password: str, session: AsyncSession) -> dict | None:
        """Authenticate user and return JWT token, or None if invalid."""
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user is None:
            return None

        if not verify_password(password, user.hashed_password):
            return None

        token = create_access_token({"sub": user.email, "user_id": user.id})
        return {"access_token": token, "token_type": "bearer"}
