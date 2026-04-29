
import datetime
import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from md_backend.models.db_models import (
    GuardianProfile,
    GuardianStatusEnum,
    StudentGuardian,
    StudentProfile,
    UserProfile,
)
from md_backend.utils.security import hash_password


class GuardianService:
    """Service for guardian operations."""

    async def create_guardian(
        self,
        first_name: str,
        last_name: str,
        email: str,
        password: str,
        phone_number: str | None = None,
        session: AsyncSession = None,
    ) -> dict | None:

        # Check if email already exists
        existing = await session.execute(select(UserProfile).where(UserProfile.email == email))
        if existing.scalar_one_or_none() is not None:
            return None

        hashed = hash_password(password)

        try:
            user_profile = UserProfile(
                first_name=first_name,
                last_name=last_name,
                email=email,
                password=hashed,
                phone_number=phone_number,
            )
            guardian_profile = GuardianProfile(
                user=user_profile,
                guardian_status=GuardianStatusEnum.WAITING,
            )
            session.add(user_profile)
            session.add(guardian_profile)
            await session.commit()
            await session.refresh(user_profile)
            await session.refresh(guardian_profile)
        except IntegrityError:
            await session.rollback()
            return None

        return self._to_response_dict(user_profile, guardian_profile, [])

    async def get_guardians(
        self,
        session: AsyncSession,
        name: str | None = None,
        email: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 10,
    ) -> dict:

        # Main query to get guardians
        query = (
            select(UserProfile, GuardianProfile)
            .options(
                selectinload(GuardianProfile.students).selectinload(StudentProfile.user),
            )
            .join(GuardianProfile, GuardianProfile.user_id == UserProfile.id)
            .where(
                UserProfile.is_active.is_(True),
                GuardianProfile.deactivated_at.is_(None),
            )
        )

        if name:
            query = query.where(
                UserProfile.first_name.ilike(f"%{name}%")
                | UserProfile.last_name.ilike(f"%{name}%")
            )

        if email:
            query = query.where(UserProfile.email.ilike(f"%{email}%"))

        if status:
            query = query.where(GuardianProfile.guardian_status == status)

        # Get total count
        count_query = select(func.count()).select_from(UserProfile).join(
            GuardianProfile, GuardianProfile.user_id == UserProfile.id
        ).where(
            UserProfile.is_active.is_(True),
            GuardianProfile.deactivated_at.is_(None),
        )

        if name:
            count_query = count_query.where(
                UserProfile.first_name.ilike(f"%{name}%")
                | UserProfile.last_name.ilike(f"%{name}%")
            )
        if email:
            count_query = count_query.where(UserProfile.email.ilike(f"%{email}%"))
        if status:
            count_query = count_query.where(GuardianProfile.guardian_status == status)

        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0

        # Paginate
        query = query.offset((page - 1) * size).limit(size)

        result = await session.execute(query)
        rows = result.all()

        items = []
        for user, guardian in rows:
            students = []
            for student in guardian.students:
                if student.deactivated_at is None:
                    students.append(
                        {
                            "user_id": str(student.user_id),
                            "first_name": student.user.first_name,
                            "last_name": student.user.last_name,
                            "email": student.user.email,
                            "birth_date": student.birth_date.isoformat() if student.birth_date else "",
                            "student_class": student.student_class.value,
                        }
                    )

            items.append(self._to_response_dict(user, guardian, students))

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        }

    async def get_guardian_by_id(
        self, session: AsyncSession, guardian_id: uuid.UUID
    ) -> dict | None:

        query = (
            select(UserProfile, GuardianProfile)
            .options(
                selectinload(GuardianProfile.students).selectinload(StudentProfile.user),
            )
            .join(GuardianProfile, GuardianProfile.user_id == UserProfile.id)
            .where(
                GuardianProfile.user_id == guardian_id,
                UserProfile.is_active.is_(True),
                GuardianProfile.deactivated_at.is_(None),
            )
        )

        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return None

        user_profile, guardian_profile = row

        # Get active students linked to this guardian
        students = []
        for student in guardian_profile.students:
            if student.deactivated_at is None:
                students.append(
                    {
                        "user_id": str(student.user_id),
                        "first_name": student.user.first_name,
                        "last_name": student.user.last_name,
                        "email": student.user.email,
                        "birth_date": student.birth_date.isoformat() if student.birth_date else "",
                        "student_class": student.student_class.value,
                    }
                )

        return self._to_response_dict(user_profile, guardian_profile, students)

    async def update_guardian(
        self,
        session: AsyncSession,
        guardian_id: uuid.UUID,
        data: dict,
    ) -> dict | None:

        query = (
            select(UserProfile, GuardianProfile)
            .options(
                selectinload(GuardianProfile.students).selectinload(StudentProfile.user),
            )
            .join(GuardianProfile, GuardianProfile.user_id == UserProfile.id)
            .where(
                GuardianProfile.user_id == guardian_id,
                UserProfile.is_active.is_(True),
                GuardianProfile.deactivated_at.is_(None),
            )
        )
        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return None

        user_profile, guardian_profile = row

        # Fields that can be updated
        user_fields = {"first_name", "last_name", "phone_number", "email"}

        # Check if email is being updated and if it's already taken
        if "email" in data and data["email"] and data["email"] != user_profile.email:
            existing = await session.execute(
                select(UserProfile).where(UserProfile.email == data["email"])
            )
            if existing.scalar_one_or_none() is not None:
                return None  # Email already taken

        for field, value in data.items():
            if value is None:
                continue
            if field in user_fields:
                setattr(user_profile, field, value)

        try:
            await session.commit()
            await session.refresh(user_profile)
            await session.refresh(guardian_profile)
        except Exception:
            await session.rollback()
            raise

        # Get updated students list
        students = []
        for student in guardian_profile.students:
            if student.deactivated_at is None:
                students.append(
                    {
                        "user_id": str(student.user_id),
                        "first_name": student.user.first_name,
                        "last_name": student.user.last_name,
                        "email": student.user.email,
                        "birth_date": student.birth_date.isoformat() if student.birth_date else "",
                        "student_class": student.student_class.value,
                    }
                )

        return self._to_response_dict(user_profile, guardian_profile, students)

    async def deactivate_guardian(
        self, session: AsyncSession, guardian_id: uuid.UUID
    ) -> bool:

        query = (
            select(UserProfile, GuardianProfile)
            .join(GuardianProfile, GuardianProfile.user_id == UserProfile.id)
            .where(
                GuardianProfile.user_id == guardian_id,
                UserProfile.is_active.is_(True),
                GuardianProfile.deactivated_at.is_(None),
            )
        )
        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return False

        user_profile, guardian_profile = row
        now = datetime.datetime.now(datetime.UTC)
        user_profile.is_active = False
        user_profile.deactivated_at = now
        guardian_profile.deactivated_at = now

        await session.commit()
        return True

    async def link_student_to_guardian(
        self,
        session: AsyncSession,
        guardian_id: uuid.UUID,
        student_id: uuid.UUID,
    ) -> bool:
        """
        Link a student to a guardian (create relationship).

        Args:
            session: Database session
            guardian_id: Guardian user_id
            student_id: Student user_id

        Returns:
            True if successful, False if already linked or not found
        """
        # Check if both exist
        guardian_result = await session.execute(
            select(GuardianProfile)
            .where(
                GuardianProfile.user_id == guardian_id,
                GuardianProfile.deactivated_at.is_(None),
            )
        )
        if guardian_result.scalar_one_or_none() is None:
            return False

        student_result = await session.execute(
            select(StudentProfile)
            .where(
                StudentProfile.user_id == student_id,
                StudentProfile.deactivated_at.is_(None),
            )
        )
        if student_result.scalar_one_or_none() is None:
            return False

        # Check if already linked
        existing = await session.execute(
            select(StudentGuardian).where(
                and_(
                    StudentGuardian.guardian_id == guardian_id,
                    StudentGuardian.student_id == student_id,
                    StudentGuardian.deactivated_at.is_(None),
                )
            )
        )
        if existing.scalar_one_or_none() is not None:
            return False  # Already linked

        try:
            link = StudentGuardian(guardian_id=guardian_id, student_id=student_id)
            session.add(link)
            await session.commit()
            return True
        except Exception:
            await session.rollback()
            return False

    async def unlink_student_from_guardian(
        self,
        session: AsyncSession,
        guardian_id: uuid.UUID,
        student_id: uuid.UUID,
    ) -> bool:
        """
        Unlink a student from a guardian (soft delete the relationship).

        Args:
            session: Database session
            guardian_id: Guardian user_id
            student_id: Student user_id

        Returns:
            True if successful, False if not found
        """
        query = select(StudentGuardian).where(
            and_(
                StudentGuardian.guardian_id == guardian_id,
                StudentGuardian.student_id == student_id,
                StudentGuardian.deactivated_at.is_(None),
            )
        )
        result = await session.execute(query)
        link = result.scalar_one_or_none()

        if link is None:
            return False

        link.deactivated_at = datetime.datetime.now(datetime.UTC)
        await session.commit()
        return True

    def _to_response_dict(
        self,
        user_profile: UserProfile,
        guardian_profile: GuardianProfile,
        students: list,
    ) -> dict:
        return {
            "user_id": str(guardian_profile.user_id),
            "first_name": user_profile.first_name,
            "last_name": user_profile.last_name,
            "email": user_profile.email,
            "phone_number": user_profile.phone_number,
            "guardian_status": guardian_profile.guardian_status.value,
            "is_active": user_profile.is_active,
            "created_at": user_profile.created_at.isoformat() if user_profile.created_at else None,
            "deactivated_at": (
                user_profile.deactivated_at.isoformat()
                if user_profile.deactivated_at
                else None
            ),
            "students": students,
        }

    def _to_list_response_dict(
        self,
        user_profile: UserProfile,
        guardian_profile: GuardianProfile,
        student_count: int,
    ) -> dict:
        """Map profiles to a list response dict."""
        return {
            "user_id": str(guardian_profile.user_id),
            "first_name": user_profile.first_name,
            "last_name": user_profile.last_name,
            "email": user_profile.email,
            "phone_number": user_profile.phone_number,
            "guardian_status": guardian_profile.guardian_status.value,
            "is_active": user_profile.is_active,
            "created_at": user_profile.created_at.isoformat() if user_profile.created_at else None,
            "quantidade_alunos": student_count,
        }
