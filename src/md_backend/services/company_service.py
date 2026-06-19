"""Service layer for Company operations."""

import datetime
import uuid

from fastapi import BackgroundTasks
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from md_backend.models.api_models import (
    CompanyBatchErrorItem,
    CompanyBatchResponse,
    CompanyBatchRow,
)
from md_backend.models.db_models import (
    CompanyProfile,
    PartnershipStatusEnum,
    SchoolCompanyPartnership,
    SponsorshipRequest,
    SponsorshipRequestStatusEnum,
    UserProfile,
)
from md_backend.services.csv_processor_service import CSVProcessorService
from md_backend.utils.email_sender import EmailSender
from md_backend.utils.names import build_full_name
from md_backend.utils.security import hash_password

COMPANY_BATCH_HEADERS = {"first_name", "last_name", "email"}

_email_sender = EmailSender()


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

    async def import_from_csv(
        self,
        raw_content: bytes,
        session: AsyncSession,
        csv_processor: CSVProcessorService,
        background_tasks: BackgroundTasks,
    ) -> CompanyBatchResponse:
        """Import companies from a CSV payload and return an import summary.

        Decodes and validates CSV rows, inserts new companies and schedules
        password emails via background tasks.
        """
        content = csv_processor.decode_csv(raw_content)
        reader = csv_processor.validate_headers(content, COMPANY_BATCH_HEADERS)
        validation = csv_processor.validate_rows(reader, CompanyBatchRow)

        if validation.has_errors:
            return CompanyBatchResponse(
                status="aborted",
                total_processed=validation.total_processed,
                created=0,
                failed=len(validation.errors),
                message="Validation failed. No records were imported.",
                errors=[
                    CompanyBatchErrorItem(
                        row=e.row,
                        email=e.email,
                        reason=e.reason,
                        first_name=e.first_name,
                        last_name=e.last_name,
                    )
                    for e in validation.errors
                ],
            )

        created = 0
        created_rows: list[tuple[str, str]] = []
        abort_error: CompanyBatchErrorItem | None = None

        for line_number, row in validation.valid_rows_with_line:
            try:
                user_result = await session.execute(
                    insert(UserProfile)
                    .values(
                        first_name=row.first_name,
                        last_name=row.last_name,
                        email=row.email,
                        password=await hash_password(uuid.uuid4().hex),
                    )
                    .returning(UserProfile.id)
                )
                user_id = user_result.scalar_one()

                await session.execute(
                    insert(CompanyProfile).values(
                        user_id=user_id,
                        spots=0,
                        available_spots=0,
                    )
                )
            except IntegrityError:
                await session.rollback()
                abort_error = CompanyBatchErrorItem(
                    row=line_number,
                    email=row.email,
                    reason="Email already registered.",
                )
                break

            created_rows.append((row.email, row.first_name))
            created += 1

        if abort_error is not None:
            return CompanyBatchResponse(
                status="aborted",
                total_processed=validation.total_processed,
                created=0,
                failed=1,
                message="Insert failed. No records were imported.",
                errors=[abort_error],
            )

        await session.commit()

        for email, first_name in created_rows:
            background_tasks.add_task(
                _email_sender.send_set_password, to_email=email, first_name=first_name
            )

        return CompanyBatchResponse(
            status="completed",
            total_processed=validation.total_processed,
            created=created,
            failed=0,
            message=f"{created} company/companies imported successfully.",
        )

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

    async def list_company_partnerships(
        self,
        company_id: uuid.UUID,
        session: AsyncSession,
        status_filter: PartnershipStatusEnum | None = None,
    ) -> dict | None:
        """Return all active partnerships for a company.

        Each item is enriched with the school name and the originating request title,
        so the caller can render the company's "supported schools" list directly.

        Returns None if the company does not exist.
        """
        company_result = await session.execute(
            select(CompanyProfile).where(CompanyProfile.user_id == company_id)
        )
        if company_result.scalar_one_or_none() is None:
            return None

        filters = [
            SchoolCompanyPartnership.company_id == company_id,
            SchoolCompanyPartnership.is_active.is_(True),
            SchoolCompanyPartnership.status != PartnershipStatusEnum.REJECTED,
        ]
        if status_filter is not None:
            filters.append(SchoolCompanyPartnership.status == status_filter)

        query = (
            select(SchoolCompanyPartnership, SponsorshipRequest, UserProfile)
            .join(
                SponsorshipRequest,
                SponsorshipRequest.id == SchoolCompanyPartnership.request_id,
            )
            .join(UserProfile, UserProfile.id == SchoolCompanyPartnership.school_id)
            .where(*filters)
            .order_by(SchoolCompanyPartnership.created_at.desc())
        )

        result = await session.execute(query)
        rows = result.all()

        items = [
            {
                "id": str(partnership.id),
                "school_id": str(partnership.school_id),
                "school_name": build_full_name(user.first_name, user.last_name),
                "company_id": str(partnership.company_id),
                "request_id": str(partnership.request_id),
                "request_title": request.title,
                "granted_spots": partnership.granted_spots,
                "status": partnership.status,
                "created_at": partnership.created_at.isoformat(),
            }
            for partnership, request, user in rows
        ]

        return {"items": items, "total": len(items)}

    async def end_partnership(
        self,
        company_id: uuid.UUID,
        partnership_id: uuid.UUID,
        session: AsyncSession,
    ) -> dict | None | str:
        """End an active partnership and free up its granted spots."""
        async with session.begin_nested():
            partnership_result = await session.execute(
                select(SchoolCompanyPartnership, SponsorshipRequest)
                .outerjoin(
                    SponsorshipRequest,
                    SponsorshipRequest.id == SchoolCompanyPartnership.request_id,
                )
                .where(
                    SchoolCompanyPartnership.id == partnership_id,
                    SchoolCompanyPartnership.company_id == company_id,
                    SchoolCompanyPartnership.is_active.is_(True),
                )
                .with_for_update(of=SchoolCompanyPartnership)
            )
            row = partnership_result.one_or_none()

            if row is None:
                return None

            partnership, sponsorship = row
            if sponsorship is None:
                return "request_not_found"

            now = datetime.datetime.now(datetime.UTC)
            partnership.is_active = False
            partnership.deactivated_at = now

            if partnership.status != PartnershipStatusEnum.REJECTED:
                sponsorship.remaining_spots = min(
                    sponsorship.requested_spots,
                    sponsorship.remaining_spots + partnership.granted_spots,
                )
                if sponsorship.remaining_spots >= sponsorship.requested_spots:
                    sponsorship.status = SponsorshipRequestStatusEnum.OPEN
                elif sponsorship.remaining_spots > 0:
                    sponsorship.status = SponsorshipRequestStatusEnum.PARTIALLY_FULFILLED
                else:
                    sponsorship.status = SponsorshipRequestStatusEnum.FULFILLED

        await session.commit()

        return {
            "id": str(partnership.id),
            "school_id": str(partnership.school_id),
            "company_id": str(partnership.company_id),
            "request_id": str(partnership.request_id),
            "granted_spots": partnership.granted_spots,
            "status": partnership.status,
            "created_at": partnership.created_at.isoformat(),
        }
