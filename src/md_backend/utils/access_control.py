"""Shared authorization helpers for student access control."""

import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import GuardianProfile, StudentGuardian


async def guardian_owns_student(
    session: AsyncSession, guardian_id: uuid.UUID, student_id: uuid.UUID
) -> bool:
    """Return True if an active guardian↔student link exists."""
    result = await session.execute(
        select(StudentGuardian).where(
            and_(
                StudentGuardian.guardian_id == guardian_id,
                StudentGuardian.student_id == student_id,
                StudentGuardian.deactivated_at.is_(None),
            )
        )
    )
    return result.scalar_one_or_none() is not None


async def is_active_guardian(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Return True if user_id belongs to an active guardian profile."""
    result = await session.execute(
        select(GuardianProfile).where(
            GuardianProfile.user_id == user_id,
            GuardianProfile.deactivated_at.is_(None),
        )
    )
    return result.scalar_one_or_none() is not None


async def can_access_student(
    session: AsyncSession,
    current_user: dict,
    student_id: uuid.UUID,
) -> bool:
    """Return True if current_user may access student_id (admin or linked guardian)."""
    if current_user.get("is_superadmin"):
        return True
    user_id = uuid.UUID(current_user["user_id"])
    return await guardian_owns_student(session=session, guardian_id=user_id, student_id=student_id)
