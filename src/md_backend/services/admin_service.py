"""Admin service for user management."""

import uuid

from helper_backend.utils.logger import get_logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from md_backend.models.db_models import (
    AdminProfile,
    CompanyProfile,
    GuardianProfile,
    GuardianStatusEnum,
    StudentProfile,
    UserProfile,
)
from md_backend.utils.names import build_full_name

logger = get_logger(__name__)
_logger_extra = {"component_name": "admin_service", "component_version": "v1",}

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


class AdminService:
    """Service for admin operations on users."""

    async def list_users(
        self,
        session: AsyncSession,
        status_filter: str | None = None,
        role: str | None = None,
    ) -> list[dict]:
        """List all users, optionally filtered by status or role."""
        logger.info(
            "Listing users",
            extra={**_logger_extra, "status_filter": status_filter, "role": role},
        )

        query = (
            select(UserProfile)
            .options(
                selectinload(UserProfile.guardian_profile),
                selectinload(UserProfile.admin_profile),
                selectinload(UserProfile.student_profile),
                selectinload(UserProfile.company_profile),
            )
            .order_by(UserProfile.created_at.desc())
        )

        guardian_joined = False

        if role == "guardian":
            logger.debug(
                "Applying guardian role filter",
                extra=_logger_extra,
            )

            query = query.join(GuardianProfile, UserProfile.guardian_profile)
            guardian_joined = True

        elif role == "student":
            logger.debug(
                "Applying student role filter",
                extra=_logger_extra,
            )

            query = query.join(StudentProfile, UserProfile.student_profile)

        elif role == "admin":
            logger.debug(
                "Applying admin role filter",
                extra=_logger_extra,
            )

            query = query.join(AdminProfile, UserProfile.admin_profile)
        elif role == "company":
            query = query.join(CompanyProfile, UserProfile.company_profile)

        if status_filter is not None:
            logger.debug(
                "Applying status filter",
                extra={**_logger_extra, "status_filter": status_filter},
            )

            guardian_status = _STATUS_INPUT_MAP[status_filter]
            if not guardian_joined:
                query = query.join(GuardianProfile, UserProfile.guardian_profile)
            query = query.where(
                GuardianProfile.guardian_status == guardian_status
            )

        result = await session.execute(query)
        users = result.scalars().all()

        logger.info(
            "Users listed successfully",
            extra={**_logger_extra, "users_count": len(users)},
        )

        return [_serialize_user(u) for u in users]

    async def update_user_status(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        new_status: str,
    ) -> dict | None:
        """Update a guardian's approval status. Returns None if user not found."""
        logger.info(
            "Updating user status",
            extra={
                **_logger_extra,
                "user_id": str(user_id),
                "new_status": new_status,
            },
        )

        result = await session.execute(
            select(UserProfile)
            .options(
                selectinload(UserProfile.guardian_profile),
                selectinload(UserProfile.admin_profile),
                selectinload(UserProfile.student_profile),
                selectinload(UserProfile.company_profile),
            )
            .where(UserProfile.id == user_id)
        )

        user = result.scalar_one_or_none()

        if user is None:
            logger.warning(
                "User not found",
                extra={**_logger_extra, "user_id": str(user_id)},
            )

            return None

        if user.admin_profile and user.admin_profile.is_superadmin:
            logger.warning(
                "Attempt to modify superadmin status",
                extra={**_logger_extra, "user_id": str(user_id)},
            )

            return {"error": "Cannot change a superadmin's status"}

        if user.guardian_profile is None:
            logger.warning(
                "User does not have guardian profile",
                extra={**_logger_extra, "user_id": str(user_id)},
            )

            return {"error": "User does not have a guardian profile"}

        old_status = user.guardian_profile.guardian_status.value

        user.guardian_profile.guardian_status = _STATUS_INPUT_MAP[new_status]

        await session.commit()

        logger.info(
            "User status updated successfully",
            extra={
                **_logger_extra,
                "user_id": str(user_id),
                "old_status": old_status,
                "new_status": new_status,
            },
        )

        return _serialize_user(user)
