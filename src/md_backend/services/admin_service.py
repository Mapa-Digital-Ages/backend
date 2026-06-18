"""Admin service for user management."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from md_backend.models.db_models import (
    AdminProfile,
    CompanyProfile,
    GuardianProfile,
    GuardianStatusEnum,
    PartnershipStatusEnum,
    SchoolCompanyPartnership,
    SponsorshipRequest,
    SponsorshipRequestStatusEnum,
    StudentProfile,
    UserProfile,
)
from md_backend.services.partnership_support_service import (
    deactivate_supported_students_for_partnership,
    sync_supported_students_for_partnership,
)
from md_backend.utils.names import build_full_name

_STATUS_INPUT_MAP = {
    "waiting": GuardianStatusEnum.WAITING,
    "approved": GuardianStatusEnum.APPROVED,
    "rejected": GuardianStatusEnum.REJECTED,
}

_STATUS_OUTPUT_MAP = {
    GuardianStatusEnum.WAITING: "waiting",
    GuardianStatusEnum.APPROVED: "approved",
    GuardianStatusEnum.REJECTED: "rejected",
}


def _derive_role(user: UserProfile) -> str:
    if user.admin_profile is not None:
        return "admin"
    if user.student_profile is not None:
        return "student"
    if user.company_profile is not None:
        return "company"
    if user.school_profile is not None:
        return "school"
    return "guardian"


def _serialize_user(user: UserProfile) -> dict:
    if user.guardian_profile is not None:
        status_str = _STATUS_OUTPUT_MAP[user.guardian_profile.guardian_status]
    else:
        status_str = "approved"
    is_superadmin = bool(user.admin_profile and user.admin_profile.is_superadmin)
    name = build_full_name(user.first_name, user.last_name)
    return {
        "id": str(user.id),
        "email": user.email,
        "name": name,
        "status": status_str,
        "role": _derive_role(user),
        "is_superadmin": is_superadmin,
        "created_at": user.created_at.isoformat(),
    }


def _partnership_status_value(status: PartnershipStatusEnum | str) -> str:
    return status.value if isinstance(status, PartnershipStatusEnum) else str(status)


def _serialize_partnership(
    partnership: SchoolCompanyPartnership,
    sponsorship: SponsorshipRequest,
    school_user: UserProfile | None,
    company_user: UserProfile | None,
) -> dict:
    school_name = (
        build_full_name(school_user.first_name, school_user.last_name)
        if school_user is not None
        else ""
    )
    company_name = (
        build_full_name(company_user.first_name, company_user.last_name)
        if company_user is not None
        else ""
    )

    return {
        "id": str(partnership.id),
        "school_id": str(partnership.school_id),
        "school_name": school_name,
        "company_id": str(partnership.company_id),
        "company_name": company_name,
        "request_id": str(partnership.request_id),
        "request_title": sponsorship.title,
        "requested_spots": sponsorship.requested_spots,
        "remaining_spots": sponsorship.remaining_spots,
        "granted_spots": partnership.granted_spots,
        "status": _partnership_status_value(partnership.status),
        "created_at": partnership.created_at.isoformat(),
    }


class AdminService:
    """Service for admin operations on users."""

    async def list_users(
        self,
        session: AsyncSession,
        status_filter: str | None = None,
        role: str | None = None,
    ) -> list[dict]:
        """List all users, optionally filtered by status or role."""
        query = (
            select(UserProfile)
            .options(
                selectinload(UserProfile.guardian_profile),
                selectinload(UserProfile.admin_profile),
                selectinload(UserProfile.student_profile),
                selectinload(UserProfile.company_profile),
                selectinload(UserProfile.school_profile),
            )
            .order_by(UserProfile.created_at.desc())
        )

        guardian_joined = False
        if role == "guardian":
            query = query.join(GuardianProfile, UserProfile.guardian_profile)
            guardian_joined = True
        elif role == "student":
            query = query.join(StudentProfile, UserProfile.student_profile)
        elif role == "admin":
            query = query.join(AdminProfile, UserProfile.admin_profile)
        elif role == "company":
            query = query.join(CompanyProfile, UserProfile.company_profile)

        if status_filter is not None:
            guardian_status = _STATUS_INPUT_MAP[status_filter]
            if not guardian_joined:
                query = query.join(GuardianProfile, UserProfile.guardian_profile)
            query = query.where(GuardianProfile.guardian_status == guardian_status)

        result = await session.execute(query)
        users = result.scalars().all()
        return [_serialize_user(u) for u in users]

    async def update_user_status(
        self, session: AsyncSession, user_id: uuid.UUID, new_status: str
    ) -> dict | None:
        """Update a guardian's approval status. Returns None if user not found."""
        result = await session.execute(
            select(UserProfile)
            .options(
                selectinload(UserProfile.guardian_profile),
                selectinload(UserProfile.admin_profile),
                selectinload(UserProfile.student_profile),
                selectinload(UserProfile.company_profile),
                selectinload(UserProfile.school_profile),
            )
            .where(UserProfile.id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return None

        if user.admin_profile and user.admin_profile.is_superadmin:
            return {"error": "Cannot change a superadmin's status"}

        if user.guardian_profile is None:
            return {"error": "User does not have a guardian profile"}

        user.guardian_profile.guardian_status = _STATUS_INPUT_MAP[new_status]
        await session.commit()

        return _serialize_user(user)

    async def list_partnerships(
        self,
        session: AsyncSession,
        status_filter: str | None = None,
    ) -> dict:
        """List all SchoolCompanyPartnership records, optionally filtered by status."""
        school_user = aliased(UserProfile)
        company_user = aliased(UserProfile)

        query = (
            select(SchoolCompanyPartnership, SponsorshipRequest, school_user, company_user)
            .join(
                SponsorshipRequest,
                SponsorshipRequest.id == SchoolCompanyPartnership.request_id,
            )
            .join(school_user, school_user.id == SchoolCompanyPartnership.school_id)
            .join(company_user, company_user.id == SchoolCompanyPartnership.company_id)
            .order_by(SchoolCompanyPartnership.created_at.desc())
        )

        if status_filter is not None:
            query = query.where(
                SchoolCompanyPartnership.status == PartnershipStatusEnum(status_filter)
            )

        result = await session.execute(query)
        rows = result.all()

        items = [
            _serialize_partnership(partnership, sponsorship, school, company)
            for partnership, sponsorship, school, company in rows
        ]

        return {"items": items, "total": len(items)}

    async def update_partnership_status(
        self,
        session: AsyncSession,
        partnership_id: uuid.UUID,
        new_status: str,
    ) -> dict | None | str:
        """Approve or reject a partnership inside a single database transaction.

        Returns:
            dict  — success, the updated partnership.
            None  — partnership not found.
            "request_not_found" — linked SponsorshipRequest missing (data integrity issue).
        """
        target_status = PartnershipStatusEnum(new_status.lower())
        school_user = aliased(UserProfile)
        company_user = aliased(UserProfile)

        async with session.begin_nested():
            # Lock the partnership row and load the display data needed by the admin UI.
            partnership_result = await session.execute(
                select(SchoolCompanyPartnership, SponsorshipRequest, school_user, company_user)
                .outerjoin(
                    SponsorshipRequest,
                    SponsorshipRequest.id == SchoolCompanyPartnership.request_id,
                )
                .outerjoin(school_user, school_user.id == SchoolCompanyPartnership.school_id)
                .outerjoin(company_user, company_user.id == SchoolCompanyPartnership.company_id)
                .where(SchoolCompanyPartnership.id == partnership_id)
                .with_for_update(of=SchoolCompanyPartnership)
            )
            row = partnership_result.one_or_none()

            if row is None:
                return None

            partnership, sponsorship, school, company = row

            if sponsorship is None:
                return "request_not_found"

            previous_status = partnership.status

            if target_status == PartnershipStatusEnum.APPROVED:
                if previous_status == PartnershipStatusEnum.REJECTED:
                    if partnership.granted_spots > sponsorship.remaining_spots:
                        return "overbooking"
                    sponsorship.remaining_spots -= partnership.granted_spots

                partnership.status = target_status

                if sponsorship.remaining_spots == 0:
                    sponsorship.status = SponsorshipRequestStatusEnum.FULFILLED
                else:
                    sponsorship.status = SponsorshipRequestStatusEnum.PARTIALLY_FULFILLED
                await sync_supported_students_for_partnership(session, partnership)

            elif target_status == PartnershipStatusEnum.REJECTED:
                partnership.status = target_status

                if previous_status != PartnershipStatusEnum.REJECTED:
                    sponsorship.remaining_spots = min(
                        sponsorship.requested_spots,
                        sponsorship.remaining_spots + partnership.granted_spots,
                    )

                # Re-evaluate the request status
                if sponsorship.remaining_spots >= sponsorship.requested_spots:
                    sponsorship.status = SponsorshipRequestStatusEnum.OPEN
                elif sponsorship.remaining_spots > 0:
                    sponsorship.status = SponsorshipRequestStatusEnum.PARTIALLY_FULFILLED
                # If remaining_spots == 0, status remains unchanged.
                await deactivate_supported_students_for_partnership(session, partnership.id)

        await session.commit()

        return _serialize_partnership(partnership, sponsorship, school, company)
