"""School Services - handles atomic creation of school accounts."""

import datetime
import secrets
import uuid

from fastapi import BackgroundTasks
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import SchoolBatchRow
from md_backend.models.db_models import (
    PartnershipStatusEnum,
    SchoolCompanyPartnership,
    SchoolProfile,
    SponsorshipRequest,
    SponsorshipRequestStatusEnum,
    StudentProfile,
    UserProfile,
)
from md_backend.services.csv_processor_service import CSVProcessorService, CSVRowError
from md_backend.services.password_reset_service import PasswordResetService
from md_backend.utils.email_sender import EmailSender
from md_backend.utils.names import build_full_name
from md_backend.utils.security import hash_password

SCHOOL_BATCH_EXPECTED_HEADERS = {
    "first_name",
    "last_name",
    "email",
    "phone_number",
    "is_private",
}


class SchoolService:
    """Service for school-related operations."""

    def __init__(
        self,
        csv_processor: CSVProcessorService | None = None,
        email_sender: EmailSender | None = None,
        password_reset_service: PasswordResetService | None = None,
    ) -> None:
        """Initialize with optional overrides (defaults to the real collaborators)."""
        self._csv_processor = csv_processor or CSVProcessorService()
        self._password_reset_service = password_reset_service or PasswordResetService(
            email_sender=email_sender
        )

    async def create_school(
        self,
        first_name: str,
        last_name: str | None,
        email: str,
        password: str,
        is_private: bool,
        session: AsyncSession,
        phone_number: str | None = None,
        requested_spots: int | None = None,
    ) -> dict | None:
        """Create a school atomically (user_profile + school_profile).

        Returns the created school dict, or None if the e-mail already exists.
        """
        existing = await session.execute(select(UserProfile).where(UserProfile.email == email))
        if existing.scalar_one_or_none() is not None:
            return None

        hashed = await hash_password(password)
        user = UserProfile(
            email=email,
            password=hashed,
            first_name=first_name,
            last_name=last_name,
            phone_number=phone_number,
        )
        session.add(user)
        await session.flush()

        school = SchoolProfile(
            user_id=user.id,
            is_private=is_private,
            requested_spots=requested_spots,
        )
        session.add(school)

        await session.commit()
        await session.refresh(user)
        await session.refresh(school)

        return self._build_school_dict(user, school, student_count=0)

    def _build_school_dict(
        self, user: UserProfile, school: SchoolProfile, student_count: int
    ) -> dict:
        """Build the response dict without exposing the password."""
        full_name = build_full_name(user.first_name, user.last_name)
        return {
            "user_id": str(user.id),
            "email": user.email,
            "name": full_name,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_private": school.is_private,
            "requested_spots": school.requested_spots,
            "is_active": user.is_active,
            "deactivated_at": school.deactivated_at.isoformat() if school.deactivated_at else None,
            "created_at": user.created_at.isoformat(),
            "student_count": student_count,
        }

    def _student_count_subq(self):
        """Correlated subquery counting students per school."""
        return (
            select(func.count(StudentProfile.user_id))
            .where(StudentProfile.school_id == SchoolProfile.user_id)
            .correlate(SchoolProfile)
            .scalar_subquery()
        )

    async def list_schools(
        self,
        session: AsyncSession,
        page: int = 1,
        size: int = 20,
        name: str | None = None,
    ) -> dict:
        """Return a paginated list of active schools with student count."""
        count_subq = self._student_count_subq()

        query = (
            select(UserProfile, SchoolProfile, count_subq.label("student_count"))
            .join(SchoolProfile, SchoolProfile.user_id == UserProfile.id)
            .where(UserProfile.is_active.is_(True))
        )

        if name:
            query = query.where(
                UserProfile.first_name.ilike(f"%{name}%") | UserProfile.last_name.ilike(f"%{name}%")
            )

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar_one()

        offset = (page - 1) * size
        result = await session.execute(query.offset(offset).limit(size))
        rows = result.all()

        items = [
            self._build_school_dict(user, school, student_count)
            for user, school, student_count in rows
        ]

        return {"items": items, "total": total, "page": page, "size": size}

    async def get_school_by_id(
        self,
        school_id: uuid.UUID,
        session: AsyncSession,
    ) -> dict | None:
        """Return a single school by its user_id, or None if not found."""
        count_subq = self._student_count_subq()

        query = (
            select(UserProfile, SchoolProfile, count_subq.label("student_count"))
            .join(SchoolProfile, SchoolProfile.user_id == UserProfile.id)
            .where(SchoolProfile.user_id == school_id)
        )

        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return None

        user, school, student_count = row
        return self._build_school_dict(user, school, student_count)

    async def update_school(
        self,
        school_id: uuid.UUID,
        first_name: str | None,
        last_name: str | None,
        email: str | None,
        is_private: bool | None,
        requested_spots: int | None,
        session: AsyncSession,
        last_name_provided: bool = False,
    ) -> dict | None | str:
        """Update school fields partially. Returns dict, None (not found), or 'email_conflict'."""
        result = await session.execute(
            select(UserProfile, SchoolProfile)
            .join(SchoolProfile, SchoolProfile.user_id == UserProfile.id)
            .where(SchoolProfile.user_id == school_id)
        )
        row = result.one_or_none()

        if row is None:
            return None

        user, school = row

        if email is not None and email != user.email:
            conflict = await session.execute(select(UserProfile).where(UserProfile.email == email))
            if conflict.scalar_one_or_none() is not None:
                return "email_conflict"
            user.email = email

        if first_name is not None:
            user.first_name = first_name
        if last_name_provided:
            user.last_name = last_name

        if is_private is not None:
            school.is_private = is_private

        if requested_spots is not None:
            school.requested_spots = requested_spots

        await session.commit()
        await session.refresh(user)
        await session.refresh(school)

        count_result = await session.execute(
            select(func.count(StudentProfile.user_id)).where(StudentProfile.school_id == school_id)
        )
        student_count = count_result.scalar_one()

        return self._build_school_dict(user, school, student_count)

    async def deactivate_school(
        self,
        school_id: uuid.UUID,
        session: AsyncSession,
    ) -> bool:
        """Soft delete: set is_active=False on user and deactivated_at on school."""
        result = await session.execute(
            select(UserProfile, SchoolProfile)
            .join(SchoolProfile, SchoolProfile.user_id == UserProfile.id)
            .where(SchoolProfile.user_id == school_id)
        )
        row = result.one_or_none()

        if row is None:
            return False

        user, school = row
        now = datetime.datetime.now(datetime.UTC)
        user.is_active = False
        user.deactivated_at = now
        school.deactivated_at = now

        await session.commit()
        return True

    async def create_sponsorship_request(
        self,
        school_id: uuid.UUID,
        title: str,
        requested_spots: int,
        session: AsyncSession,
        description: str | None = None,
    ) -> dict | None:
        """Create a sponsorship request for a school.

        Returns the created request dict, or None if the school does not exist.
        """
        school_result = await session.execute(
            select(SchoolProfile).where(SchoolProfile.user_id == school_id)
        )
        school = school_result.scalar_one_or_none()

        if school is None:
            return None

        sponsorship = SponsorshipRequest(
            school_id=school_id,
            title=title,
            description=description,
            requested_spots=requested_spots,
            remaining_spots=requested_spots,
            status=SponsorshipRequestStatusEnum.OPEN,
        )
        session.add(sponsorship)
        await session.commit()
        await session.refresh(sponsorship)

        return self._build_sponsorship_dict(sponsorship)

    async def list_sponsorship_requests(
        self,
        school_id: uuid.UUID,
        session: AsyncSession,
    ) -> dict | None:
        """Return all sponsorship requests for a school.

        Returns None if the school does not exist.
        """
        school_result = await session.execute(
            select(SchoolProfile).where(SchoolProfile.user_id == school_id)
        )
        school = school_result.scalar_one_or_none()

        if school is None:
            return None

        result = await session.execute(
            select(SponsorshipRequest)
            .where(SponsorshipRequest.school_id == school_id)
            .order_by(SponsorshipRequest.created_at.desc())
        )
        requests = result.scalars().all()

        return {
            "items": [self._build_sponsorship_dict(r) for r in requests],
            "total": len(requests),
        }

    async def list_school_partnerships(
        self,
        school_id: uuid.UUID,
        session: AsyncSession,
        status_filter: PartnershipStatusEnum | None = None,
    ) -> dict | None:
        """Return all active partnerships for a school.

        Each item is enriched with the company name and the originating request title,
        so the school can see who accepted its requests and the partnership status.
        Rejected partnerships are never returned.

        Returns None if the school does not exist.
        """
        school_result = await session.execute(
            select(SchoolProfile).where(SchoolProfile.user_id == school_id)
        )
        if school_result.scalar_one_or_none() is None:
            return None

        filters = [
            SchoolCompanyPartnership.school_id == school_id,
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
            .join(UserProfile, UserProfile.id == SchoolCompanyPartnership.company_id)
            .where(*filters)
            .order_by(SchoolCompanyPartnership.created_at.desc())
        )

        result = await session.execute(query)
        rows = result.all()

        items = [
            {
                "id": str(partnership.id),
                "school_id": str(partnership.school_id),
                "company_id": str(partnership.company_id),
                "company_name": build_full_name(user.first_name, user.last_name),
                "request_id": str(partnership.request_id),
                "request_title": request.title,
                "granted_spots": partnership.granted_spots,
                "status": partnership.status,
                "created_at": partnership.created_at.isoformat(),
            }
            for partnership, request, user in rows
        ]

        return {"items": items, "total": len(items)}

    def _build_sponsorship_dict(self, request: SponsorshipRequest) -> dict:
        """Build the sponsorship request response dict."""
        return {
            "id": str(request.id),
            "school_id": str(request.school_id),
            "title": request.title,
            "description": request.description,
            "requested_spots": request.requested_spots,
            "remaining_spots": request.remaining_spots,
            "status": request.status,
            "created_at": request.created_at.isoformat(),
        }

    async def list_public_sponsorship_requests(
        self,
        session: AsyncSession,
    ) -> dict:
        """Return all OPEN or PARTIALLY_FULFILLED sponsorship requests with school name."""
        from md_backend.models.db_models import SponsorshipRequestStatusEnum

        query = (
            select(SponsorshipRequest, UserProfile)
            .join(SchoolProfile, SchoolProfile.user_id == SponsorshipRequest.school_id)
            .join(UserProfile, UserProfile.id == SchoolProfile.user_id)
            .where(
                SponsorshipRequest.status.in_(
                    [
                        SponsorshipRequestStatusEnum.OPEN,
                        SponsorshipRequestStatusEnum.PARTIALLY_FULFILLED,
                    ]
                )
            )
            .order_by(SponsorshipRequest.created_at.desc())
        )

        result = await session.execute(query)
        rows = result.all()

        items = [
            {
                "id": str(req.id),
                "school_id": str(req.school_id),
                "school_name": build_full_name(user.first_name, user.last_name),
                "title": req.title,
                "description": req.description,
                "requested_spots": req.requested_spots,
                "remaining_spots": req.remaining_spots,
                "status": req.status,
                "created_at": req.created_at.isoformat(),
            }
            for req, user in rows
        ]

        return {"items": items, "total": len(items)}

    async def import_school_batch(
        self,
        raw_content: bytes,
        session: AsyncSession,
        background_tasks: BackgroundTasks | None = None,
    ) -> dict:
        """..."""
        content = self._csv_processor.decode_csv(raw_content)
        reader = self._csv_processor.validate_headers(content, SCHOOL_BATCH_EXPECTED_HEADERS)
        schema_result = self._csv_processor.validate_rows(reader, SchoolBatchRow)

        integrity_errors = await self._check_duplicate_emails(
            valid_rows_with_line=schema_result.valid_rows_with_line,
            session=session,
        )

        all_errors = sorted(schema_result.errors + integrity_errors, key=lambda err: err.row)
        total_processed = schema_result.total_processed

        # ← Filtra emails que falharam na checagem de integridade
        duplicate_emails = {err.email for err in integrity_errors}
        rows_to_insert = [
            row for row in schema_result.valid_rows if row.email not in duplicate_emails
        ]

        if not rows_to_insert:
            return self._build_partial_payload(
                total_processed=total_processed,
                created=0,
                errors=all_errors,
            )

        return await self._persist_school_batch(
            valid_rows=rows_to_insert,
            total_processed=total_processed,
            errors=all_errors,
            session=session,
            background_tasks=background_tasks,
        )

    async def _check_duplicate_emails(
        self,
        valid_rows_with_line: list[tuple[int, SchoolBatchRow]],
        session: AsyncSession,
    ) -> list[CSVRowError]:
        """Run the single integrity query and flag any email already in use."""
        if not valid_rows_with_line:
            return []

        emails_to_check = {row.email for _, row in valid_rows_with_line}
        result = await session.execute(
            select(UserProfile.email).where(UserProfile.email.in_(emails_to_check))
        )
        existing_emails = set(result.scalars().all())

        if not existing_emails:
            return []

        return [
            CSVRowError(
                row=line_number,
                email=row.email,
                reason="Email já cadastrado no sistema",
                first_name=row.first_name,
                last_name=row.last_name or "",
                phone_number=row.phone_number or "",
                is_private=str(row.is_private),
            )
            for line_number, row in valid_rows_with_line
            if row.email in existing_emails
        ]

    def _build_partial_payload(
        self,
        total_processed: int,
        created: int,
        errors: list[CSVRowError],
    ) -> dict:
        """Build the response payload for a partial or fully-failed import."""
        if created == 0:
            message = (
                "Nenhum registro foi salvo. Todos os registros apresentaram erros de validação."
            )
        else:
            message = (
                f"{created} escola(s) importada(s) com sucesso. "
                f"{len(errors)} registro(s) ignorado(s) por erros de validação."
            )
        return {
            "status": "partial" if created > 0 else "aborted",
            "total_processed": total_processed,
            "created": created,
            "failed": len(errors),
            "message": message,
            "errors": [
                {
                    "row": err.row,
                    "email": err.email,
                    "reason": err.reason,
                    "first_name": err.first_name or None,
                    "last_name": err.last_name or None,
                    "phone_number": err.phone_number or None,
                    "is_private": err.is_private or None,
                }
                for err in errors
            ],
        }

    async def _persist_school_batch(
        self,
        valid_rows: list[SchoolBatchRow],
        total_processed: int,
        errors: list[CSVRowError],
        session: AsyncSession,
        background_tasks: BackgroundTasks | None,
    ) -> dict:
        users_payload = []
        for row in valid_rows:
            raw_password = secrets.token_urlsafe(16)
            users_payload.append(
                {
                    "id": uuid.uuid4(),
                    "email": row.email,
                    "first_name": row.first_name,
                    "last_name": row.last_name,
                    "phone_number": row.phone_number,
                    "password": await hash_password(raw_password),
                }
            )

        stmt_users = (
            insert(UserProfile).values(users_payload).returning(UserProfile.id, UserProfile.email)
        )
        inserted_users = (await session.execute(stmt_users)).all()

        rows_by_email = {row.email: row for row in valid_rows}
        schools_payload = [
            {"user_id": user_id, "is_private": rows_by_email[email].is_private}
            for user_id, email in inserted_users
        ]
        await session.execute(insert(SchoolProfile).values(schools_payload))

        reset_notifications = []
        for user_id, email in inserted_users:
            reset_code = await self._password_reset_service.prepare_initial_password_setup(
                user_id=user_id,
                session=session,
            )
            reset_notifications.append((email, reset_code))

        await session.commit()

        for email, reset_code in reset_notifications:
            await self._password_reset_service.dispatch_initial_password_setup_email(
                email=email,
                code=reset_code,
                background_tasks=background_tasks,
            )

        if errors:
            return self._build_partial_payload(
                total_processed=total_processed,
                created=len(inserted_users),
                errors=errors,
            )

        return {
            "status": "completed",
            "total_processed": total_processed,
            "created": len(inserted_users),
            "failed": 0,
            "message": f"{len(inserted_users)} escola(s) importada(s) com sucesso.",
            "errors": [],
        }
