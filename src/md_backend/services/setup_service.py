"""Setup service for creating the first superadmin."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import User, UserStatus
from md_backend.utils.security import hash_password


class SetupService:
    """Service for initial platform setup."""

    async def create_superadmin(
        self, email: str, password: str, session: AsyncSession
    ) -> dict | None:
        """Create the first superadmin. Returns None if a superadmin already exists."""
        result = await session.execute(select(User).where(User.is_superadmin.is_(True)))
        if result.scalar_one_or_none() is not None:
            return None

        hashed = hash_password(password)
        user = User(
            email=email,
            hashed_password=hashed,
            status=UserStatus.APROVADO,
            is_superadmin=True,
        )
        session.add(user)
        await session.commit()
        return {"detail": "Superadmin criado com sucesso"}
