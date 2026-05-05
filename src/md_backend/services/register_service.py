"""Register service for user registration."""

import datetime
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
        """Register a new guardian. Returns success dict or None if email already exists."""
        result = await session.execute(select(UserProfile).where(UserProfile.email == email))
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
        guardian = GuardianProfile(user=user, guardian_status=GuardianStatusEnum.WAITING)
        session.add(user)
        session.add(guardian)

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return None

        return {"id": str(user.id), "detail": "Registration completed. Awaiting approval."}

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
        """Register a new student. Returns success dict or None if email already exists."""
        result = await session.execute(select(UserProfile).where(UserProfile.email == email))
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
            await session.rollback()
            return None

        return {"id": str(user.id), "detail": "Registration completed."}
