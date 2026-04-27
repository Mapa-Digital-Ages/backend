"""Register service for user registration."""

import datetime

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


def _split_name(name: str) -> tuple[str, str]:
    parts = name.split(" ", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


class RegisterService:
    """Service for handling user registration."""

    async def register_responsavel(
        self, email: str, password: str, name: str, session: AsyncSession
    ) -> dict | None:
        """Register a new responsavel. Returns success dict or None if email already exists."""
        result = await session.execute(select(UserProfile).where(UserProfile.email == email))
        if result.scalar_one_or_none() is not None:
            return None

        first_name, last_name = _split_name(name)
        hashed = hash_password(password)
        user = UserProfile(
            email=email,
            password=hashed,
            first_name=first_name,
            last_name=last_name,
        )
        guardian = GuardianProfile(user=user, guardian_status=GuardianStatusEnum.WAITING)
        session.add(user)
        session.add(guardian)

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return None

        return {"id": str(user.id), "detail": "Cadastro realizado. Aguardando aprovacao."}

    async def register_aluno(
        self,
        email: str,
        password: str,
        name: str,
        birth_date: datetime.date,
        student_class: ClassEnum,
        session: AsyncSession,
    ) -> dict | None:
        """Register a new aluno. Returns success dict or None if email already exists."""
        result = await session.execute(select(UserProfile).where(UserProfile.email == email))
        if result.scalar_one_or_none() is not None:
            return None

        first_name, last_name = _split_name(name)
        hashed = hash_password(password)
        user = UserProfile(
            email=email,
            password=hashed,
            first_name=first_name,
            last_name=last_name,
        )
        student = StudentProfile(user=user, birth_date=birth_date, student_class=student_class)
        session.add(user)
        session.add(student)

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return None

        return {"id": str(user.id), "detail": "Cadastro realizado."}
