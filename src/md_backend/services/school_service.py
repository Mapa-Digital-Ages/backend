"""School Services - handles atomic creation of school accounts."""

import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import (
    SchoolProfile,
    SponsorshipRequest,
    SponsorshipRequestStatusEnum,
    StudentProfile,
    UserProfile,
)
from md_backend.utils.names import build_full_name
from md_backend.utils.security import hash_password


class SchoolService:
    """Service for school-related operations."""

    async def create_school(
        self,
        first_name: str,
        last_name: str | None,
        email: str,
        password: str,
        is_private: bool,
        session: AsyncSession,
        phone_number: str | None = None,
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
            "is_private": school.is_private,
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
        requested_spots: int,
        session: AsyncSession,
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

    def _build_sponsorship_dict(self, request: SponsorshipRequest) -> dict:
        """Build the sponsorship request response dict."""
        return {
            "id": str(request.id),
            "school_id": str(request.school_id),
            "requested_spots": request.requested_spots,
            "remaining_spots": request.remaining_spots,
            "status": request.status,
            "created_at": request.created_at.isoformat(),
        }
