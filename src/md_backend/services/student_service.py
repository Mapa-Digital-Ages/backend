"""Student service for student registration."""

import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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