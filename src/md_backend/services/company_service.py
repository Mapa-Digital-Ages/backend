"""Company Services - handles atomic creation of company accounts."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import Company, RoleEnum, User, UserStatus
from md_backend.utils.security import hash_password


class CompanyService:
    """Service for company-related operations."""

    async def create_company(
        self,
        first_name: str,
        last_name: str,
        email: str,
        password: str,
        cnpj: str,
        spots: int,
        session: AsyncSession,
    ) -> dict | None:
        """Create a company atomically (user_profile + company_profile)."""
        existing = await session.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none() is not None:
            return None

        hashed = hash_password(password)
        full_name = f"{first_name} {last_name}"

        user = User(
            email=email,
            hashed_password=hashed,
            name=full_name,
            role=RoleEnum.EMPRESA,
            status=UserStatus.AGUARDANDO,
        )
        session.add(user)

        await session.flush()

        company = Company(
            user_id=user.id,
            cnpj=cnpj,
            spots=spots,
            available_spots=spots,
        )
        session.add(company)

        await session.commit()

        return {
            "user_id": user.id,
            "email": user.email,
            "name": user.name,
            "cnpj": company.cnpj,
            "spots": company.spots,
            "available_spots": company.available_spots,
            "status": user.status.value,
            "created_at": user.created_at.isoformat(),
        }
