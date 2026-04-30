"""Guardian service for guardian listing and detail retrieval."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import or_

from md_backend.models.db_models import (
    GuardianProfile,
    GuardianStatusEnum,
    StudentGuardian,
    UserProfile,
)


class GuardianService:
    """Service for guardian queries."""

    async def get_guardians(
        self,
        session: AsyncSession,
        page: int = 1,
        size: int = 10,
        name: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """List active guardians with optional name and status filters."""
        query = (
            select(UserProfile, GuardianProfile)
            .join(GuardianProfile, UserProfile.guardian_profile)
            .where(UserProfile.is_active.is_(True))
            .order_by(UserProfile.created_at.desc())
        )

        if name:
            query = query.where(
                or_(
                    UserProfile.first_name.ilike(f"%{name}%"),
                    UserProfile.last_name.ilike(f"%{name}%"),
                )
            )

        status_enum = self._parse_status_filter(status)
        if status_enum is not None:
            query = query.where(GuardianProfile.guardian_status == status_enum)

        query = query.offset((page - 1) * size).limit(size)

        result = await session.execute(query)
        rows = result.all()
        return [self._serialize_guardian(user, guardian) for user, guardian in rows]

    async def get_guardian_by_id(
        self, session: AsyncSession, guardian_id: uuid.UUID
    ) -> dict | None:
        """Get one guardian with profile data and linked student IDs."""
        query = (
            select(UserProfile, GuardianProfile)
            .join(GuardianProfile, UserProfile.guardian_profile)
            .where(UserProfile.id == guardian_id)
        )
        result = await session.execute(query)
        row = result.one_or_none()
        if row is None:
            return None

        user_profile, guardian_profile = row
        students = await self._get_linked_students(session, guardian_id)

        payload = self._serialize_guardian(user_profile, guardian_profile)
        payload["students"] = students
        return payload

    async def _get_linked_students(
        self, session: AsyncSession, guardian_id: uuid.UUID
    ) -> list[str]:
        result = await session.execute(
            select(StudentGuardian.student_id).where(StudentGuardian.guardian_id == guardian_id)
        )
        return [str(student_id) for (student_id,) in result.all()]

    def _serialize_guardian(
        self, user_profile: UserProfile, guardian_profile: GuardianProfile
    ) -> dict:
        return {
            "id": str(user_profile.id),
            "first_name": user_profile.first_name,
            "last_name": user_profile.last_name,
            "email": user_profile.email,
            "phone_number": user_profile.phone_number or "",
            "guardian_status": guardian_profile.guardian_status.value,
        }

    def _parse_status_filter(
        self, status: str | GuardianStatusEnum | None
    ) -> GuardianStatusEnum | None:
        if status is None:
            return None
        if isinstance(status, GuardianStatusEnum):
            return status
        return GuardianStatusEnum(status)
