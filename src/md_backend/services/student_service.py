"""Student service for student registration."""

import datetime
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from helper_backend.utils.logger import get_logger
from md_backend.models.db_models import (
    Attempt,
    ClassEnum,
    Content,
    StudentContentProgress,
    StudentGuardian,
    StudentProfile,
    Subject,
    Task,
    TaskStatusEnum,
    UserProfile,
    WellBeing,
)
from md_backend.utils.security import hash_password

logger = get_logger(__name__)
_logger_extra = {"component_name": "student_service","component_version": "v1",}

_TASK_STATUS_TO_FRONTEND = {
    TaskStatusEnum.DONE: "done",
    TaskStatusEnum.PENDING: "pending",
}


class StudentService:
    """Service for student operations."""

    async def create_student(
        self,
        first_name: str,
        last_name: str,
        email: str,
        password: str,
        birth_date: datetime.date,
        student_class: ClassEnum,
        session: AsyncSession,
        phone_number: str | None = None,
        school_id: uuid.UUID | None = None,
    ) -> dict | None:
        """Create a student atomically."""

        logger.info(
            "Creating student",
            extra={
                **_logger_extra,
                "email": email,
                "student_class": student_class.value,
            },
        )

        existing = await session.execute(
            select(UserProfile).where(UserProfile.email == email)
        )

        if existing.scalar_one_or_none() is not None:
            logger.warning(
                "Student creation failed: email already exists",
                extra={
                    **_logger_extra,
                    "email": email,
                },
            )

            return None

        hashed = await hash_password(password)

        try:
            user_profile = UserProfile(
                first_name=first_name,
                last_name=last_name,
                email=email,
                password=hashed,
                phone_number=phone_number,
            )

            student_profile = StudentProfile(
                user=user_profile,
                birth_date=birth_date,
                student_class=student_class,
                school_id=school_id,
            )

            session.add(user_profile)
            session.add(student_profile)

            await session.commit()

            await session.refresh(user_profile)
            await session.refresh(student_profile)

            logger.info(
                "Student created successfully",
                extra={
                    **_logger_extra,
                    "student_id": str(student_profile.user_id),
                    "email": email,
                },
            )

        except IntegrityError:
            await session.rollback()

            logger.exception(
                "Student creation failed due to integrity error",
                extra={
                    **_logger_extra,
                    "email": email,
                },
            )

            return None

        return self._to_dict(user_profile, student_profile)

    async def get_students(
        self,
        session: AsyncSession,
        name: str | None = None,
        email: str | None = None,
        page: int = 1,
        size: int = 10,
    ) -> list[dict]:
        """List active students with pagination."""

        logger.info(
            "Listing students",
            extra={
                **_logger_extra,
                "page": page,
                "size": size,
                "name_filter": name,
                "email_filter": email,
            },
        )

        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(
                UserProfile.is_active.is_(True),
                StudentProfile.deactivated_at.is_(None),
            )
        )

        if name:
            query = query.where(
                UserProfile.first_name.ilike(f"%{name}%")
                | UserProfile.last_name.ilike(f"%{name}%")
            )

        if email:
            query = query.where(
                UserProfile.email.ilike(f"%{email}%")
            )

        query = query.offset((page - 1) * size).limit(size)

        result = await session.execute(query)

        rows = result.all()

        logger.info(
            "Students listed successfully",
            extra={
                **_logger_extra,
                "students_count": len(rows),
            },
        )

        return [
            self._to_dict(user, student)
            for user, student in rows
        ]

    async def get_student_by_id(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
    ) -> dict | None:
        """Get a student by user_id."""

        logger.info(
            "Getting student by id",
            extra={
                **_logger_extra,
                "student_id": str(student_id),
            },
        )

        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(
                StudentProfile.user_id == student_id,
                UserProfile.is_active.is_(True),
                StudentProfile.deactivated_at.is_(None),
            )
        )

        result = await session.execute(query)

        row = result.one_or_none()

        if row is None:
            logger.warning(
                "Student not found",
                extra={
                    **_logger_extra,
                    "student_id": str(student_id),
                },
            )

            return None

        user_profile, student_profile = row

        return self._to_dict(
            user_profile,
            student_profile,
        )
