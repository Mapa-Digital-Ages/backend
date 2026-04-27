"""School Services - handles atomic creation of school accounts."""

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import RoleEnum, School, User, UserStatus, Student
from md_backend.utils.security import hash_password

class SchoolService:
    """Service for school-related operations."""

    async def create_school(
        self,
        first_name: str,
        last_name: str,
        email: str,
        password: str,
        is_private: bool,
        cnpj: str,
        session: AsyncSession,
    ) -> dict | None:
        """Create a school atomically (user_profile + school_profile).
        
        Returns the created school dict, or None if the e-mail already exists.
        Raises IntegrityError propagated to the caller when school insert fails
        after user insert (triggering rollback at the caller level)."""
    
        existing = await session.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none() is not None:
            return None
    
        hashed = hash_password(password)
        full_name = f"{first_name} {last_name}"

        user = User(
            email=email,
            hashed_password=hashed,
            name=full_name,
            role=RoleEnum.ESCOLA,
            status=UserStatus.APROVADO,
        )
        session.add(user)

        await session.flush()

        school = School(
            user_id=user.id,
            cnpj=cnpj,
            is_private=is_private,
        )
        session.add(school)

        await session.commit()

        return {
            "user_id": user.id,
            "email": user.email,
            "name": user.name,
            "cnpj": school.cnpj,
            "is_private": school.is_private,
            "status": user.status.value,
            "created_at": user.created_at.isoformat(),
        }
    
    def _build_school_dict(self, user, school, quantidade_alunos: int) -> dict:
        """Monta o dict de resposta sem expor senha."""
        return {
            "user_id": user.id,
            "email": user.email,
            "name": user.name,
            "cnpj": school.cnpj,
            "is_private": school.is_private,
            "status": user.status.value,
            "created_at": user.created_at.isoformat(),
            "is_active": school.is_active,
            "quantidade_alunos": quantidade_alunos,
        }

    def _student_count_subq(self):
        """Subquery correlacionada que conta alunos por escola."""
        return (
            select(func.count(Student.id))
            .where(Student.school_id == School.user_id)
            .correlate(School)
            .scalar_subquery()
        )

    async def list_schools(
        self,
        session: AsyncSession,
        page: int = 1,
        size: int = 20,
        name: str | None = None,
        cnpj: str | None = None,
    ) -> dict:
        """Return a paginated list of active schools with student count."""
        count_subq = self._student_count_subq()

        query = (
            select(User, School, count_subq.label("quantidade_alunos"))
            .join(School, School.user_id == User.id)
            .where(School.is_active == True)  # noqa: E712
        )

        if name:
            query = query.where(User.name.ilike(f"%{name}%"))
        if cnpj:
            query = query.where(School.cnpj == cnpj)

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar_one()

        offset = (page - 1) * size
        result = await session.execute(query.offset(offset).limit(size))
        rows = result.all()

        items = [
            self._build_school_dict(user, school, quantidade_alunos)
            for user, school, quantidade_alunos in rows
        ]

        return {"items": items, "total": total, "page": page, "size": size}

    async def get_school_by_id(
        self,
        school_id: int,
        session: AsyncSession,
    ) -> dict | None:
        """Return a single school by its user_id, or None if not found."""
        count_subq = self._student_count_subq()

        query = (
            select(User, School, count_subq.label("quantidade_alunos"))
            .join(School, School.user_id == User.id)
            .where(School.user_id == school_id)
        )

        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return None

        user, school, quantidade_alunos = row
        return self._build_school_dict(user, school, quantidade_alunos)

    async def update_school(
        self,
        school_id: int,
        first_name: str | None,
        last_name: str | None,
        email: str | None,
        is_private: bool | None,
        cnpj: str | None,
        session: AsyncSession,
    ) -> dict | None | str:
        """Update school fields partially. Returns dict, None (not found), or 'email_conflict'."""
        result = await session.execute(
            select(User, School)
            .join(School, School.user_id == User.id)
            .where(School.user_id == school_id)
        )
        row = result.one_or_none()

        if row is None:
            return None

        user, school = row

        if email is not None and email != user.email:
            conflict = await session.execute(select(User).where(User.email == email))
            if conflict.scalar_one_or_none() is not None:
                return "email_conflict"
            user.email = email

        if first_name is not None or last_name is not None:
            parts = user.name.split(" ", 1)
            current_first = parts[0]
            current_last = parts[1] if len(parts) > 1 else ""
            user.name = f"{first_name or current_first} {last_name or current_last}".strip()

        if is_private is not None:
            school.is_private = is_private

        if cnpj is not None:
            school.cnpj = cnpj

        await session.commit()
        await session.refresh(user)
        await session.refresh(school)

        count_subq = self._student_count_subq()
        count_result = await session.execute(
            select(count_subq.label("quantidade_alunos"))
        )
        quantidade_alunos = count_result.scalar_one()

        return self._build_school_dict(user, school, quantidade_alunos)

    async def deactivate_school(
        self,
        school_id: int,
        session: AsyncSession,
    ) -> bool:
        """Soft delete: set is_active=False and deactivated_at=now(). Returns False if not found."""
        import datetime

        result = await session.execute(
            select(School).where(School.user_id == school_id)
        )
        school = result.scalar_one_or_none()

        if school is None:
            return False

        school.is_active = False
        school.deactivated_at = datetime.datetime.now(datetime.UTC)

        await session.commit()
        return True
        
