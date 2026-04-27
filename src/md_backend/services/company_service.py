import uuid
import datetime
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import CompanyProfile, UserProfile
from md_backend.utils.security import hash_password


class CompanyService:
    """Service for company-related operations."""

    async def create_company(
        self,
        first_name: str,
        last_name: str,
        email: str,
        password: str,
        spots: int,
        session: AsyncSession,
    ) -> dict | None:
        """Create a company atomically (user_profile + company_profile)."""
        existing = await session.execute(select(UserProfile).where(UserProfile.email == email))
        if existing.scalar_one_or_none() is not None:
            return None

        hashed = hash_password(password)

        user = UserProfile(
            email=email,
            password=hashed,
            first_name=first_name,
            last_name=last_name,
        )
        session.add(user)

        await session.flush()

        company = CompanyProfile(
            user_id=user.id,
            spots=spots,
            available_spots=spots,
        )
        session.add(company)

        await session.commit()

        full_name = f"{first_name} {last_name}".strip()
        return {
            "user_id": str(user.id),
            "email": user.email,
            "phone_number": user.phone_number,
            "name": full_name,
            "spots": company.spots,
            "available_spots": company.available_spots,
            "status": "aguardando",
            "created_at": user.created_at.isoformat(),
        }
    async def list_companies(
        self, 
        session: AsyncSession, 
        name: str | None = None, 
        page: int = 1, 
        size: int = 10
    ) -> list[dict]:
        """List all active companies with filtering and pagination."""
        offset = (page - 1) * size
        
        query = (
            select(CompanyProfile)
            .join(UserProfile)
            .where(UserProfile.is_active == True)
            .options(selectinload(CompanyProfile.user))
        )

        if name:
            search = f"%{name}%"
            query = query.where(
                (UserProfile.first_name.ilike(search)) | 
                (UserProfile.last_name.ilike(search))
            )

        query = query.offset(offset).limit(size)
        
        result = await session.execute(query)
        companies = result.scalars().all()

        return [
            {
                "user_id": str(c.user_id),
                "email": c.user.email,
                "phone_number": c.user.phone_number,
                "name": f"{c.user.first_name} {c.user.last_name}".strip(),
                "spots": c.spots,
                "available_spots": c.available_spots,
                "status": "aguardando",
                "created_at": c.user.created_at.isoformat(),
            }
            for c in companies
        ]

    async def get_company_by_id(self, user_id: uuid.UUID, session: AsyncSession) -> dict | None:
        """Get a single active company by user_id."""
        query = (
            select(CompanyProfile)
            .join(UserProfile)
            .where((CompanyProfile.user_id == user_id) & (UserProfile.is_active == True))
            .options(selectinload(CompanyProfile.user))
        )
        result = await session.execute(query)
        c = result.scalar_one_or_none()

        if not c:
            return None

        return {
            "user_id": str(c.user_id),
            "email": c.user.email,
            "phone_number": c.user.phone_number,
            "name": f"{c.user.first_name} {c.user.last_name}".strip(),
            "spots": c.spots,
            "available_spots": c.available_spots,
            "status": "aguardando",
            "created_at": c.user.created_at.isoformat(),
        }

    async def delete_company(self, user_id: uuid.UUID, session: AsyncSession) -> bool:
        """Soft delete a company (deactivate user)."""
        user = await session.get(UserProfile, user_id)
        if not user or not user.is_active:
            return False

        user.is_active = False
        user.deactivated_at = datetime.datetime.now(datetime.timezone.utc)
        
        await session.commit()
        return True

    async def update_company(
        self,
        user_id: uuid.UUID,
        session: AsyncSession,
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        phone_number: str | None = None,
        spots: int | None = None,
        is_active: bool | None = None,
    ) -> dict | None:
        """Update company and user data with robust business rules."""
        query = (
            select(CompanyProfile)
            .where(CompanyProfile.user_id == user_id)
            .options(selectinload(CompanyProfile.user))
        )
        result = await session.execute(query)
        company = result.scalar_one_or_none()

        if not company:
            return None

        if first_name is not None:
            company.user.first_name = first_name
        if last_name is not None:
            company.user.last_name = last_name
        if email is not None:
            company.user.email = email
        if phone_number is not None:
            company.user.phone_number = phone_number
            
        if is_active is not None:
            company.user.is_active = is_active
            if is_active:
                company.user.deactivated_at = None
            else:
                company.user.deactivated_at = datetime.datetime.now(datetime.timezone.utc)

        if spots is not None:
            occupied_spots = company.spots - company.available_spots
            
            if spots < occupied_spots:
                from fastapi import HTTPException, status
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Nao e possivel reduzir o total de vagas para {spots} pois {occupied_spots} vagas ja estao ocupadas."
                )
            
            company.spots = spots
            company.available_spots = spots - occupied_spots

        await session.commit()

        return {
            "user_id": str(company.user_id),
            "email": company.user.email,
            "phone_number": company.user.phone_number,
            "name": f"{company.user.first_name} {company.user.last_name}".strip(),
            "spots": company.spots,
            "available_spots": company.available_spots,
            "status": "aguardando",
            "created_at": company.user.created_at.isoformat(),
        }
