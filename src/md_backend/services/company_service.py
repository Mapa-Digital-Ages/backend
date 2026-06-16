"""Service layer for Company operations."""

import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from md_backend.models.db_models import CompanyProfile, SchoolCompanyPartnership, UserProfile
from md_backend.utils.names import build_full_name
from md_backend.utils.security import hash_password


class CompanyService:
    """Service for company-related operations."""

    async def create_company(
        self,
        first_name: str,
        last_name: str | None,
        email: str,
        password: str,
        spots: int,
        session: AsyncSession,
    ) -> dict | None:
        """Create a company atomically (user_profile + company_profile)."""
        existing = await session.execute(select(UserProfile).where(UserProfile.email == email))
        if existing.scalar_one_or_none() is not None:
            return None

        hashed = await hash_password(password)

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

        full_name = build_full_name(first_name, last_name)
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
        self, session: AsyncSession, name: str | None = None, page: int = 1, size: int = 10
    ) -> list[dict]:
        """List all active companies with filtering and pagination."""
        offset = (page - 1) * size

        query = (
            select(CompanyProfile)
            .join(UserProfile)
            .where(UserProfile.is_active)
            .options(selectinload(CompanyProfile.user))
        )

        if name:
            search = f"%{name}%"
            query = query.where(
                (UserProfile.first_name.ilike(search)) | (UserProfile.last_name.ilike(search))
            )

        query = query.offset(offset).limit(size)

        result = await session.execute(query)
        companies = result.scalars().all()

        return [
            {
                "user_id": str(c.user_id),
                "email": c.user.email,
                "phone_number": c.user.phone_number,
                "name": build_full_name(c.user.first_name, c.user.last_name),
                "spots": c.spots,
                "available_spots": c.available_spots,
                "status": "aguardando",
                "created_at": c.user.created_at.isoformat(),
            }
            for c in companies
        ]

    async def count_companies(
        self,
        session: AsyncSession,
        name: str | None = None,
    ) -> int:
        """Return the total count of active companies, optionally filtered by name."""
        conditions: list[ColumnElement[bool]] = [
            UserProfile.is_active.is_(True),
            CompanyProfile.deactivated_at.is_(None),
        ]
        if name:
            conditions.append(
                UserProfile.first_name.ilike(f"%{name}%") | UserProfile.last_name.ilike(f"%{name}%")
            )

        query = (
            select(func.count(UserProfile.id))
            .join(CompanyProfile, CompanyProfile.user_id == UserProfile.id)
            .where(*conditions)
        )
        return (await session.execute(query)).scalar() or 0

    async def get_company_by_id(self, user_id: uuid.UUID, session: AsyncSession) -> dict | None:
        """Get a single active company by user_id."""
        query = (
            select(CompanyProfile)
            .join(UserProfile)
            .where((CompanyProfile.user_id == user_id) & UserProfile.is_active)
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
            "name": build_full_name(c.user.first_name, c.user.last_name),
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
        user.deactivated_at = datetime.datetime.now(datetime.UTC)

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
        last_name_provided: bool = False,
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
        if last_name_provided:
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
                company.user.deactivated_at = datetime.datetime.now(datetime.UTC)

        if spots is not None:
            occupied_spots = company.spots - company.available_spots

            if spots < occupied_spots:
                from fastapi import HTTPException, status

                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Nao e possivel reduzir o total de vagas para {spots} "
                        f"pois {occupied_spots} vagas ja estao ocupadas."
                    ),
                )

            company.spots = spots
            company.available_spots = spots - occupied_spots

        await session.commit()

        return {
            "user_id": str(company.user_id),
            "email": company.user.email,
            "phone_number": company.user.phone_number,
            "name": build_full_name(company.user.first_name, company.user.last_name),
            "spots": company.spots,
            "status": "aguardando",
            "created_at": company.user.created_at.isoformat(),
        }

    async def create_partnership(
        self,
        company_id: uuid.UUID,
        request_id: uuid.UUID,
        granted_spots: int,
        session: AsyncSession,
    ) -> dict | str | None:
        """Create a donation intent (partnership) for a sponsorship request.

        Returns:
            dict  — success, the created partnership.
            None  — company or sponsorship request not found.
            "overbooking" — granted_spots exceeds remaining_spots.
        """
        from md_backend.models.db_models import (
            CompanyProfile,
            PartnershipStatusEnum,
            SponsorshipRequest,
            SponsorshipRequestStatusEnum,
        )

        # Verify company exists
        company_result = await session.execute(
            select(CompanyProfile).where(CompanyProfile.user_id == company_id)
        )
        if company_result.scalar_one_or_none() is None:
            return None

        # Lock the sponsorship request row to prevent overbooking under concurrency
        req_result = await session.execute(
            select(SponsorshipRequest).where(SponsorshipRequest.id == request_id).with_for_update()
        )
        sponsorship = req_result.scalar_one_or_none()

        if sponsorship is None:
            return None

        if granted_spots > sponsorship.remaining_spots:
            return "overbooking"

        # Reserve spots
        sponsorship.remaining_spots -= granted_spots

        # Update sponsorship status
        if sponsorship.remaining_spots == 0:
            sponsorship.status = SponsorshipRequestStatusEnum.FULFILLED
        else:
            sponsorship.status = SponsorshipRequestStatusEnum.PARTIALLY_FULFILLED

        partnership = SchoolCompanyPartnership(
            school_id=sponsorship.school_id,
            company_id=company_id,
            request_id=request_id,
            granted_spots=granted_spots,
            status=PartnershipStatusEnum.PENDING,
        )
        session.add(partnership)

        await session.commit()
        await session.refresh(partnership)

        return {
            "id": str(partnership.id),
            "school_id": str(partnership.school_id),
            "company_id": str(partnership.company_id),
            "request_id": str(partnership.request_id),
            "granted_spots": partnership.granted_spots,
            "status": partnership.status,
            "created_at": partnership.created_at.isoformat(),
        }
