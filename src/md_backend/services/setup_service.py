"""Setup service for creating the first superadmin."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import AdminProfile, UserProfile
from md_backend.utils.security import hash_password


def _split_name(name: str) -> tuple[str, str]:
    parts = name.split(" ", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


class SetupService:
    """Service for initial platform setup."""

    async def create_superadmin(
        self, email: str, password: str, name: str, session: AsyncSession
    ) -> dict | None:
        """Create the first superadmin. Returns None if a superadmin already exists."""
        result = await session.execute(
            select(AdminProfile).where(AdminProfile.is_superadmin.is_(True))
        )
        if result.scalar_one_or_none() is not None:
            return None

        first_name, last_name = _split_name(name)
        hashed = hash_password(password)
        user = UserProfile(
            email=email,
            password=hashed,
            first_name=first_name,
            last_name=last_name,
        )
        admin = AdminProfile(user=user, is_superadmin=True)
        session.add(user)
        session.add(admin)
        await session.commit()
        return {"id": str(user.id), "detail": "Superadmin criado com sucesso"}
