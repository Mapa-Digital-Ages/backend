"""School Services - handles atomic creation of school accounts."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import RoleEnum, School, User, UserStatus
from md_backend.utils.security import hash_password


class SchoolService:
    """Service for school-related operations."""

    async def create_school(
        self,
        first_name: str,
        last_name: str,
        email: str,
        password: str,
        is_private: bool,
        cnpj: str,
        session: AsyncSession,
    ) -> dict | None:
        """Create a school atomically (user_profile + school_profile).

        Returns the created school dict, or None if the e-mail already exists.
        Raises IntegrityError propagated to the caller when school insert fails
        after user insert (triggering rollback at the caller level).
        """
        existing = await session.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none() is not None:
            return None

        hashed = hash_password(password)
        full_name = f"{first_name} {last_name}"

        user = User(
            email=email,
            hashed_password=hashed,
            name=full_name,
            role=RoleEnum.ESCOLA,
            status=UserStatus.APROVADO,
        )
        session.add(user)

        await session.flush()

        school = School(
            user_id=user.id,
            cnpj=cnpj,
            is_private=is_private,
        )
        session.add(school)

        await session.commit()

        return {
            "user_id": user.id,
            "email": user.email,
            "name": user.name,
            "cnpj": school.cnpj,
            "is_private": school.is_private,
            "status": user.status.value,
            "created_at": user.created_at.isoformat(),
        }
