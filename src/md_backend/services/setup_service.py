"""Setup service for creating the first superadmin."""

from helper_backend.utils.logger import get_logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import (
    AdminProfile,
    UserProfile,
)
from md_backend.utils.security import hash_password

logger = get_logger(__name__)
_logger_extra = {
    "component_name": "setup_service",
    "component_version": "v1",
}


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
        """Create the first superadmin."""
        logger.info(
            "Creating superadmin",
            extra={
                **_logger_extra,
                "email": email,
            },
        )

        result = await session.execute(
            select(AdminProfile).where(AdminProfile.issuperadmin.is_(True))
        )

        if result.scalar_one_or_none() is not None:
            logger.warning(
                "Superadmin already exists",
                extra={
                    **_logger_extra,
                    "email": email,
                },
            )

            return None

        hashed = await hash_password(password)

        user = UserProfile(
            email=email,
            password=hashed,
            first_name=first_name,
            last_name=last_name,
            phone_number=phone_number,
        )

        admin = AdminProfile(
            user=user,
            is_superadmin=True,
        )

        session.add(user)
        session.add(admin)

        await session.commit()

        logger.info(
            "Superadmin created successfully",
            extra={
                **_logger_extra,
                "user_id": str(user.id),
                "email": email,
            },
        )

        return {
            "id": str(user.id),
            "detail": "Superadmin created successfully",
        }
