"""Support allocation helpers for approved school-company partnerships."""

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import (
    PartnershipStatusEnum,
    PartnershipStudentSupport,
    SchoolCompanyPartnership,
    StudentProfile,
    UserProfile,
)


async def sync_supported_students_for_partnership(
    session: AsyncSession,
    partnership: SchoolCompanyPartnership,
) -> None:
    """Create or reactivate student support rows for an approved partnership."""
    existing_result = await session.execute(
        select(PartnershipStudentSupport)
        .where(PartnershipStudentSupport.partnership_id == partnership.id)
        .with_for_update()
    )
    existing_supports = existing_result.scalars().all()
    support_by_student = {support.student_id: support for support in existing_supports}

    students_result = await session.execute(
        select(StudentProfile)
        .join(UserProfile, UserProfile.id == StudentProfile.user_id)
        .where(
            StudentProfile.school_id == partnership.school_id,
            StudentProfile.deactivated_at.is_(None),
            UserProfile.is_active.is_(True),
        )
        .order_by(UserProfile.created_at.asc(), UserProfile.id.asc())
        .limit(partnership.granted_spots)
    )
    target_student_ids = [student.user_id for student in students_result.scalars().all()]
    target_student_id_set = set(target_student_ids)
    now = datetime.datetime.now(datetime.UTC)

    for support in existing_supports:
        if support.student_id in target_student_id_set:
            support.is_active = True
            support.deactivated_at = None
        elif support.is_active:
            support.is_active = False
            support.deactivated_at = now

    for student_id in target_student_ids:
        if student_id in support_by_student:
            continue
        session.add(
            PartnershipStudentSupport(
                partnership_id=partnership.id,
                school_id=partnership.school_id,
                company_id=partnership.company_id,
                student_id=student_id,
            )
        )


async def sync_supported_students_for_school(
    session: AsyncSession,
    school_id: uuid.UUID,
) -> None:
    """Fill available support spots for every approved partnership of a school."""
    partnerships_result = await session.execute(
        select(SchoolCompanyPartnership)
        .where(
            SchoolCompanyPartnership.school_id == school_id,
            SchoolCompanyPartnership.status == PartnershipStatusEnum.APPROVED,
            SchoolCompanyPartnership.is_active.is_(True),
        )
        .order_by(
            SchoolCompanyPartnership.created_at.asc(),
            SchoolCompanyPartnership.id.asc(),
        )
        .with_for_update()
    )

    for partnership in partnerships_result.scalars().all():
        await sync_supported_students_for_partnership(session, partnership)


async def deactivate_supported_students_for_partnership(
    session: AsyncSession,
    partnership_id: uuid.UUID,
) -> None:
    """Deactivate supported students for a partnership that is no longer valid."""
    result = await session.execute(
        select(PartnershipStudentSupport)
        .where(
            PartnershipStudentSupport.partnership_id == partnership_id,
            PartnershipStudentSupport.is_active.is_(True),
        )
        .with_for_update()
    )
    now = datetime.datetime.now(datetime.UTC)
    for support in result.scalars().all():
        support.is_active = False
        support.deactivated_at = now
