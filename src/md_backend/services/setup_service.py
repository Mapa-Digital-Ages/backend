"""Setup service for creating the first superadmin."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import AdminProfile, UserProfile
from md_backend.utils.security import hash_password


class SetupService:
    """Service for initial platform setup."""

    async def create_superadmin(
        self,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        session: AsyncSession,
        phone_number: str | None = None,
    ) -> dict | None:
        """Create the first superadmin. Returns None if a superadmin already exists."""
        result = await session.execute(
            select(AdminProfile).where(AdminProfile.is_superadmin.is_(True))
        )
        if result.scalar_one_or_none() is not None:
            return None

        hashed = await hash_password(password)
        user = UserProfile(
            email=email,
            password=hashed,
            first_name=first_name,
            last_name=last_name,
            phone_number=phone_number,
        )
        admin = AdminProfile(user=user, is_superadmin=True)
        session.add(user)
        session.add(admin)
        await session.commit()
        return {"id": str(user.id), "detail": "Superadmin created successfully"}
