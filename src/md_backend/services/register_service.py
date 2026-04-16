"""Register service for user registration."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import RoleEnum, User, UserStatus
from md_backend.utils.security import hash_password


class RegisterService:
    """Service for handling user registration."""

    async def register_responsavel(
        self, email: str, password: str, name: str, session: AsyncSession
    ) -> dict | None:
        """Register a new user. Returns success dict or None if email already exists."""
        result = await session.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none() is not None:
            return None

        hashed = hash_password(password)
        user = User(
            email=email,
            hashed_password=hashed,
            name=name,
            role=RoleEnum.RESPONSAVEL,
            status=UserStatus.AGUARDANDO,
        )
        session.add(user)

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return None

        return {"detail": "Cadastro realizado. Aguardando aprovacao."}

    async def register_aluno(
        self, email: str, password: str, name: str, session: AsyncSession
    ) -> dict | None:
        """Register a new user. Returns success dict or None if email already exists."""
        result = await session.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none() is not None:
            return None

        hashed = hash_password(password)
        user = User(
            email=email,
            hashed_password=hashed,
            name=name,
            role=RoleEnum.ALUNO,
        )
        session.add(user)

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return None

        return {"detail": "Cadastro realizado."}
