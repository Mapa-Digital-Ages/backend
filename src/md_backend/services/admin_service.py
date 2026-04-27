"""Admin service for user management."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from md_backend.models.db_models import (
    AdminProfile,
    GuardianProfile,
    GuardianStatusEnum,
    StudentProfile,
    UserProfile,
)

_STATUS_INPUT_MAP = {
    "aguardando": GuardianStatusEnum.WAITING,
    "aprovado": GuardianStatusEnum.APPROVED,
    "negado": GuardianStatusEnum.REJECTED,
}

_STATUS_OUTPUT_MAP = {
    GuardianStatusEnum.WAITING: "aguardando",
    GuardianStatusEnum.APPROVED: "aprovado",
    GuardianStatusEnum.REJECTED: "negado",
}


def _derive_role(user: UserProfile) -> str:
    if user.admin_profile is not None:
        return "admin"
    if user.student_profile is not None:
        return "aluno"
    return "responsavel"


def _serialize_user(user: UserProfile) -> dict:
    if user.guardian_profile is not None:
        status_str = _STATUS_OUTPUT_MAP[user.guardian_profile.guardian_status]
    else:
        status_str = "aprovado"
    is_superadmin = bool(user.admin_profile and user.admin_profile.is_superadmin)
    name = f"{user.first_name} {user.last_name}".strip()
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
        query = (
            select(UserProfile)
            .options(
                selectinload(UserProfile.guardian_profile),
                selectinload(UserProfile.admin_profile),
                selectinload(UserProfile.student_profile),
            )
            .order_by(UserProfile.created_at.desc())
        )

        if role == "responsavel":
            query = query.join(GuardianProfile, UserProfile.guardian_profile)
        elif role == "aluno":
            query = query.join(StudentProfile, UserProfile.student_profile)
        elif role == "admin":
            query = query.join(AdminProfile, UserProfile.admin_profile)

        if status_filter is not None:
            guardian_status = _STATUS_INPUT_MAP[status_filter]
            query = query.join(GuardianProfile, UserProfile.guardian_profile).where(
                GuardianProfile.guardian_status == guardian_status
            )

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
            )
            .where(UserProfile.id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return None

        if user.admin_profile and user.admin_profile.is_superadmin:
            return {"error": "Nao e possivel alterar status de um superadmin"}

        if user.guardian_profile is None:
            return {"error": "Usuario nao possui perfil de responsavel"}

        user.guardian_profile.guardian_status = _STATUS_INPUT_MAP[new_status]
        await session.commit()

        return _serialize_user(user)
