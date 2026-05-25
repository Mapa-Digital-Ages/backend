"""School Services - handles atomic creation of school accounts."""

import datetime
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import (
    SchoolProfile,
    StudentProfile,
    UserProfile,
)
from md_backend.utils.security import hash_password

logger = logging.getLogger(__name__)
_logger_extra = {
    "component_name": "school_service",
    "component_version": "v1",
}


class SchoolService:
    """Service for school-related operations."""

    async def create_school(
        self,
        first_name: str,
        last_name: str,
        email: str,
        password: str,
        is_private: bool,
        session: AsyncSession,
        phone_number: str | None = None,
        requested_spots: int | None = None,
    ) -> dict | None:
        """Create a school atomically."""
        logger.info(
            "Creating school",
            extra={
                **_logger_extra,
                "email": email,
                "is_private": is_private,
            },
        )

        existing = await session.execute(select(UserProfile).where(UserProfile.email == email))

        if existing.scalar_one_or_none() is not None:
            logger.warning(
                "School creation failed: email already exists",
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

        session.add(user)

        await session.flush()

        school = SchoolProfile(
            user_id=user.id,
            is_private=is_private,
            requested_spots=requested_spots,
        )

        session.add(school)

        await session.commit()

        await session.refresh(user)
        await session.refresh(school)

        logger.info(
            "School created successfully",
            extra={
                **_logger_extra,
                "user_id": str(user.id),
                "email": email,
            },
        )

        return self._build_school_dict(
            user,
            school,
            student_count=0,
        )

    def _build_school_dict(
        self,
        user: UserProfile,
        school: SchoolProfile,
        student_count: int,
    ) -> dict:
        """Build the school response dict."""
        full_name = f"{user.first_name} {user.last_name}".strip()

        return {
            "user_id": str(user.id),
            "email": user.email,
            "name": full_name,
            "is_private": school.is_private,
            "requested_spots": school.requested_spots,
            "is_active": user.is_active,
            "deactivated_at": (
                school.deactivated_at.isoformat() if school.deactivated_at else None
            ),
            "created_at": user.created_at.isoformat(),
            "student_count": student_count,
        }

    def _student_count_subq(self):
        """Correlated subquery counting students per school."""
        return (
            select(func.count(StudentProfile.user_id))
            .where(StudentProfile.school_id == SchoolProfile.user_id)
            .correlate(SchoolProfile)
            .scalar_subquery()
        )

    async def list_schools(
        self,
        session: AsyncSession,
        page: int = 1,
        size: int = 20,
        name: str | None = None,
    ) -> dict:
        """Return a paginated list of active schools."""
        logger.info(
            "Listing schools",
            extra={
                **_logger_extra,
                "page": page,
                "size": size,
                "name_filter": name,
            },
        )

        count_subq = self._student_count_subq()

        query = (
            select(
                UserProfile,
                SchoolProfile,
                count_subq.label("student_count"),
            )
            .join(SchoolProfile, SchoolProfile.user_id == UserProfile.id)
            .where(UserProfile.is_active.is_(True))
        )

        if name:
            query = query.where(
                UserProfile.first_name.ilike(f"%{name}%") | UserProfile.last_name.ilike(f"%{name}%")
            )

        count_query = select(func.count()).select_from(query.subquery())

        total_result = await session.execute(count_query)

        total = total_result.scalar_one()

        offset = (page - 1) * size

        result = await session.execute(query.offset(offset).limit(size))

        rows = result.all()

        items = [
            self._build_school_dict(user, school, student_count)
            for user, school, student_count in rows
        ]

        logger.info(
            "Schools listed successfully",
            extra={
                **_logger_extra,
                "schools_count": len(items),
                "total": total,
            },
        )

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        }

    async def get_school_by_id(
        self,
        school_id: uuid.UUID,
        session: AsyncSession,
    ) -> dict | None:
        """Return a single school by its user_id."""
        logger.info(
            "Getting school by id",
            extra={
                **_logger_extra,
                "school_id": str(school_id),
            },
        )

        count_subq = self._student_count_subq()

        query = (
            select(
                UserProfile,
                SchoolProfile,
                count_subq.label("student_count"),
            )
            .join(SchoolProfile, SchoolProfile.user_id == UserProfile.id)
            .where(SchoolProfile.user_id == school_id)
        )

        result = await session.execute(query)

        row = result.one_or_none()

        if row is None:
            logger.warning(
                "School not found",
                extra={
                    **_logger_extra,
                    "school_id": str(school_id),
                },
            )

            return None

        user, school, student_count = row

        return self._build_school_dict(
            user,
            school,
            student_count,
        )

    async def update_school(
        self,
        school_id: uuid.UUID,
        first_name: str | None,
        last_name: str | None,
        email: str | None,
        is_private: bool | None,
        requested_spots: int | None,
        session: AsyncSession,
    ) -> dict | None | str:
        """Update school fields partially."""
        logger.info(
            "Updating school",
            extra={
                **_logger_extra,
                "school_id": str(school_id),
            },
        )

        result = await session.execute(
            select(UserProfile, SchoolProfile)
            .join(SchoolProfile, SchoolProfile.user_id == UserProfile.id)
            .where(SchoolProfile.user_id == school_id)
        )

        row = result.one_or_none()

        if row is None:
            logger.warning(
                "School not found",
                extra={
                    **_logger_extra,
                    "school_id": str(school_id),
                },
            )

            return None

        user, school = row

        if email is not None and email != user.email:
            conflict = await session.execute(select(UserProfile).where(UserProfile.email == email))

            if conflict.scalar_one_or_none() is not None:
                logger.warning(
                    "School update failed: email conflict",
                    extra={
                        **_logger_extra,
                        "school_id": str(school_id),
                        "email": email,
                    },
                )

                return "email_conflict"

            user.email = email

        if first_name is not None:
            user.first_name = first_name

        if last_name is not None:
            user.last_name = last_name

        if is_private is not None:
            school.is_private = is_private

        if requested_spots is not None:
            school.requested_spots = requested_spots

        await session.commit()

        await session.refresh(user)
        await session.refresh(school)

        count_result = await session.execute(
            select(func.count(StudentProfile.user_id)).where(StudentProfile.school_id == school_id)
        )

        student_count = count_result.scalar_one()

        logger.info(
            "School updated successfully",
            extra={
                **_logger_extra,
                "school_id": str(school_id),
            },
        )

        return self._build_school_dict(
            user,
            school,
            student_count,
        )

    async def deactivate_school(
        self,
        school_id: uuid.UUID,
        session: AsyncSession,
    ) -> bool:
        """Soft delete a school."""
        logger.info(
            "Deactivating school",
            extra={
                **_logger_extra,
                "school_id": str(school_id),
            },
        )

        result = await session.execute(
            select(UserProfile, SchoolProfile)
            .join(SchoolProfile, SchoolProfile.user_id == UserProfile.id)
            .where(SchoolProfile.user_id == school_id)
        )

        row = result.one_or_none()

        if row is None:
            logger.warning(
                "School not found",
                extra={
                    **_logger_extra,
                    "school_id": str(school_id),
                },
            )

            return False

        user, school = row

        now = datetime.datetime.now(datetime.UTC)

        user.is_active = False
        user.deactivated_at = now
        school.deactivated_at = now

        await session.commit()

        logger.info(
            "School deactivated successfully",
            extra={
                **_logger_extra,
                "school_id": str(school_id),
            },
        )

        return True
