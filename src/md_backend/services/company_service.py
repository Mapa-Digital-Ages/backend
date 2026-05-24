"""Service layer for Company operations."""

import datetime
import uuid

from helper_backend.utils.logger import get_logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from md_backend.models.db_models import CompanyProfile, UserProfile
from md_backend.utils.names import build_full_name
from md_backend.utils.security import hash_password

logger = get_logger(__name__)

_logger_extra = {"component_name": "company_service", "component_version": "v1"}


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
        logger.info(
            "Creating company",
            extra={
                **_logger_extra,
                "email": email,
                "spots": spots,
            },
        )

        existing = await session.execute(
            select(UserProfile).where(UserProfile.email == email)
        )

        if existing.scalar_one_or_none() is not None:
            logger.warning(
                "Company already exists",
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

        logger.info(
            "Company created successfully",
            extra={
                **_logger_extra,
                "user_id": str(user.id),
                "email": email,
            },
        )

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
        size: int = 10,
    ) -> list[dict]:
        """List all active companies with filtering and pagination."""
        logger.info(
            "Listing companies",
            extra={
                **_logger_extra,
                "name_filter": name,
                "page": page,
                "size": size,
            },
        )

        offset = (page - 1) * size

        query = (
            select(CompanyProfile)
            .join(UserProfile)
            .where(UserProfile.is_active)
            .options(selectinload(CompanyProfile.user))
        )

        if name:
            logger.debug(
                "Applying company name filter",
                extra={
                    **_logger_extra,
                    "name_filter": name,
                },
            )

            search = f"%{name}%"

            query = query.where(
                (UserProfile.first_name.ilike(search))
                | (UserProfile.last_name.ilike(search))
            )

        query = query.offset(offset).limit(size)

        result = await session.execute(query)

        companies = result.scalars().all()

        logger.info(
            "Companies listed successfully",
            extra={
                **_logger_extra,
                "companies_count": len(companies),
            },
        )

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
                UserProfile.first_name.ilike(f"%{name}%")
                | UserProfile.last_name.ilike(f"%{name}%")
            )

        query = (
            select(func.count(UserProfile.id))
            .join(CompanyProfile, CompanyProfile.user_id == UserProfile.id)
            .where(*conditions)
        )
        return (await session.execute(query)).scalar() or 0

    async def get_company_by_id(
        self,
        user_id: uuid.UUID,
        session: AsyncSession,
    ) -> dict | None:
        """Get a single active company by user_id."""
        logger.info(
            "Getting company by id",
            extra={
                **_logger_extra,
                "user_id": str(user_id),
            },
        )

        query = (
            select(CompanyProfile)
            .join(UserProfile)
            .where((CompanyProfile.user_id == user_id) & UserProfile.is_active)
            .options(selectinload(CompanyProfile.user))
        )

        result = await session.execute(query)

        c = result.scalar_one_or_none()

        if not c:
            logger.warning(
                "Company not found",
                extra={
                    **_logger_extra,
                    "user_id": str(user_id),
                },
            )

            return None

        logger.info(
            "Company retrieved successfully",
            extra={
                **_logger_extra,
                "user_id": str(user_id),
            },
        )

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

    async def delete_company(
        self,
        user_id: uuid.UUID,
        session: AsyncSession,
    ) -> bool:
        """Soft delete a company (deactivate user)."""
        logger.info(
            "Deleting company",
            extra={
                **_logger_extra,
                "user_id": str(user_id),
            },
        )

        user = await session.get(UserProfile, user_id)

        if not user or not user.is_active:
            logger.warning(
                "Company not found or already inactive",
                extra={
                    **_logger_extra,
                    "user_id": str(user_id),
                },
            )

            return False

        user.is_active = False
        user.deactivated_at = datetime.datetime.now(datetime.UTC)

        await session.commit()

        logger.info(
            "Company deleted successfully",
            extra={
                **_logger_extra,
                "user_id": str(user_id),
            },
        )

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
        logger.info(
            "Updating company",
            extra={
                **_logger_extra,
                "user_id": str(user_id),
            },
        )

        query = (
            select(CompanyProfile)
            .where(CompanyProfile.user_id == user_id)
            .options(selectinload(CompanyProfile.user))
        )

        result = await session.execute(query)

        company = result.scalar_one_or_none()

        if not company:
            logger.warning(
                "Company not found",
                extra={
                    **_logger_extra,
                    "user_id": str(user_id),
                },
            )

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
                company.user.deactivated_at = datetime.datetime.now(
                    datetime.UTC
                )

        if spots is not None:
            occupied_spots = company.spots - company.available_spots

            if spots < occupied_spots:
                logger.error(
                    "Invalid company spots update",
                    extra={
                        **_logger_extra,
                        "user_id": str(user_id),
                        "requested_spots": spots,
                        "occupied_spots": occupied_spots,
                    },
                )

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

        logger.info(
            "Company updated successfully",
            extra={
                **_logger_extra,
                "user_id": str(user_id),
            },
        )

        return {
            "user_id": str(company.user_id),
            "email": company.user.email,
            "phone_number": company.user.phone_number,
            "name": build_full_name(
                company.user.first_name, company.user.last_name
            ),
            "spots": company.spots,
            "available_spots": company.available_spots,
            "status": "aguardando",
            "created_at": company.user.created_at.isoformat(),
        }