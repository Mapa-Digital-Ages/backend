"""Student service for student registration."""

import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from md_backend.models.db_models import RoleEnum, StudentProfile, UserProfile, UserStatus
from md_backend.utils.security import hash_password


class StudentService:
    """Service for student operations."""

    async def create_student(
        self,
        first_name: str,
        last_name: str,
        email: str,
        password: str,
        birth_date: datetime.date,
        student_class: str,
        session: AsyncSession,
    ) -> dict | None:
        """Create a student atomically across user_profile and student_profile."""
        hashed = hash_password(password)

        try:
            user_profile = UserProfile(
                first_name=first_name,
                last_name=last_name,
                email=email,
                hashed_password=hashed,
                role=RoleEnum.ALUNO,
                status=UserStatus.APROVADO,
                birth_date=birth_date,
            )
            session.add(user_profile)
            await session.flush()

            student_profile = StudentProfile(
                user_id=user_profile.id,
                student_class=student_class,
            )
            session.add(student_profile)

            await session.commit()

        except IntegrityError:
            await session.rollback()
            return None
        except Exception:
            await session.rollback()
            raise

        return {
            "id": student_profile.id,
            "user_id": user_profile.id,
            "first_name": user_profile.first_name,
            "last_name": user_profile.last_name,
            "email": user_profile.email,
            "birth_date": user_profile.birth_date.isoformat(),
            "student_class": student_profile.student_class,
            "created_at": user_profile.created_at.isoformat() if user_profile.created_at else None,
        }
    
    async def get_students(
        self,
        session: AsyncSession,
        name: str | None = None,
        email: str | None = None,
        page: int = 1,
        size: int = 10,
    ) -> list[dict]:
        """List all active students with optional filters and pagination."""

        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(UserProfile.is_active.is_(True))
        )

        if name:
            query = query.where(
                UserProfile.first_name.ilike(f"%{name}%")
                | UserProfile.last_name.ilike(f"%{name}%")
            )

        if email:
            query = query.where(UserProfile.email.ilike(f"%{email}%"))

        query = query.offset((page - 1) * size).limit(size)

        result = await session.execute(query)
        rows = result.all()

        return [self._to_dict(user, student) for user, student in rows]

    async def get_student_by_id(
        self, session: AsyncSession, student_id: int
    ) -> dict | None:
        """Get a student by student_profile id."""
        from sqlalchemy import select

        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(StudentProfile.id == student_id)
        )

        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return None

        user_profile, student_profile = row
        return self._to_dict(user_profile, student_profile)
    
    async def update_student(
        self,
        session: AsyncSession,
        student_id: int,
        data: dict,
    ) -> dict | None:
        """Update a student's data. Returns None if not found."""
        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(StudentProfile.id == student_id)
        )
        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return None

        user_profile, student_profile = row

        user_fields = {"first_name", "last_name", "phone_number", "birth_date"}
        student_fields = {"student_class", "school_id"}

        for field, value in data.items():
            if value is None:
                continue
            if field in user_fields:
                setattr(user_profile, field, value)
            elif field in student_fields:
                setattr(student_profile, field, value)

        try:
            await session.commit()
            await session.refresh(user_profile)
            await session.refresh(student_profile)
        except Exception:
            await session.rollback()
            raise

        return self._to_dict(user_profile, student_profile)

    async def deactivate_student(
        self, session: AsyncSession, student_id: int
    ) -> bool:
        """Soft delete a student by setting is_active to False."""
        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(StudentProfile.id == student_id)
        )
        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return False

        user_profile, _ = row
        user_profile.is_active = False
        user_profile.deactivated_at = datetime.datetime.now(datetime.UTC)

        await session.commit()
        return True


    def _to_dict(self, user_profile: UserProfile, student_profile: StudentProfile) -> dict:
        """Map user_profile and student_profile to a full response dict."""
        return {
            "id": student_profile.id,
            "user_id": user_profile.id,
            "first_name": user_profile.first_name,
            "last_name": user_profile.last_name,
            "email": user_profile.email,
            "phone_number": user_profile.phone_number or "",
            "birth_date": user_profile.birth_date.isoformat() if user_profile.birth_date else "",
            "student_class": student_profile.student_class,
            "school_id": str(student_profile.school_id) if student_profile.school_id else "",
            "is_active": user_profile.is_active,
            "created_at": user_profile.created_at.isoformat() if user_profile.created_at else None,
        }