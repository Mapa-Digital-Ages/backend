"""Register service for user registration."""

import datetime
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import (
    ClassEnum,
    GuardianProfile,
    GuardianStatusEnum,
    StudentProfile,
    UserProfile,
)
from md_backend.utils.security import hash_password

logger = logging.getLogger(__name__)
_logger_extra = {
    "component_name": "register_service",
    "component_version": "v1",
}


class RegisterService:
    """Service for handling user registration."""

    async def register_guardian(
        self,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        session: AsyncSession,
        phone_number: str | None = None,
    ) -> dict | None:
        """Register a new guardian."""
        logger.info(
            "Registering guardian",
            extra={
                **_logger_extra,
                "email": email,
            },
        )

        result = await session.execute(select(UserProfile).where(UserProfile.email == email))

        if result.scalar_one_or_none() is not None:
            logger.warning(
                "Guardian registration failed: email already exists",
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

        guardian = GuardianProfile(
            user=user,
            guardian_status=GuardianStatusEnum.WAITING,
        )

        session.add(user)
        session.add(guardian)

        try:
            await session.commit()

        except IntegrityError:
            logger.error(
                "Guardian registration failed due to integrity error",
                extra={
                    **_logger_extra,
                    "email": email,
                },
            )

            await session.rollback()

            return None

        logger.info(
            "Guardian registered successfully",
            extra={
                **_logger_extra,
                "user_id": str(user.id),
                "email": email,
            },
        )

        return {
            "id": str(user.id),
            "detail": "Registration completed. Awaiting approval.",
        }

    async def register_student(
        self,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        birth_date: datetime.date,
        student_class: ClassEnum,
        session: AsyncSession,
        phone_number: str | None = None,
        school_id: uuid.UUID | None = None,
    ) -> dict | None:
        """Register a new student."""
        logger.info(
            "Registering student",
            extra={
                **_logger_extra,
                "email": email,
                "student_class": student_class.value,
            },
        )

        result = await session.execute(select(UserProfile).where(UserProfile.email == email))

        if result.scalar_one_or_none() is not None:
            logger.warning(
                "Student registration failed: email already exists",
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

        student = StudentProfile(
            user=user,
            birth_date=birth_date,
            student_class=student_class,
            school_id=school_id,
        )

        session.add(user)
        session.add(student)

        try:
            await session.commit()

        except IntegrityError:
            logger.error(
                "Student registration failed due to integrity error",
                extra={
                    **_logger_extra,
                    "email": email,
                },
            )

            await session.rollback()

            return None

        logger.info(
            "Student registered successfully",
            extra={
                **_logger_extra,
                "user_id": str(user.id),
                "email": email,
                "student_class": student_class.value,
            },
        )

        return {
            "id": str(user.id),
            "detail": "Registration completed.",
        }
