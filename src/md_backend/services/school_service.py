"""School Services - handles atomic creation of school accounts."""

from sqlalchemy import func, select
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
        after user insert (triggering rollback at the caller level).
        """
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
    
    async def list_schools(
            self,
            session: AsyncSession,
            page: int = 1,
            size: int = 20,
            name: str | None = None,
            cnpj: str | None = None,
    ) -> dict:
        """Return a paginated list of active schools with student count."""
        count_subq = (
            select(func.count(Student.id))
            .where(Student.school_id == School.user_id)
            .correlate(School)
            .scalar_subquery()
        )

        query = (
            select(User, School, count_subq.label("quantidade_alunos"))
            .join(School, School.user_id == User.id)
            .where(User.status == UserStatus.APROVADO)
        )

        if name:
            query = query.where(User.name.ilike(f"%{name}%"))
        if cnpj:
            query = query.where(School.cnpj == cnpj)

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar_one()

        offset = (page - 1) * size
        query = query.offset(offset).limit(size)
        result = await session.execute(query)
        rows = result.all()

        items = [
            {
                "user_id": User.id,
                "email": User.email,
                "name": User.name,
                "cnpj": School.cnpj,
                "is_private": School.is_private,
                "status": User.status.value,
                "created_at": User.created_at.isoformat(),
                "is_active": User.status == UserStatus.APROVADO,
                "quantidade_alunos": quantidade_alunos,
            }
            for User. School, quantidade_alunos in rows
        ]

        return {"items": items, "total": total, "page": page, "size": size}
    
    async def get_schools_by_id(
            self,
            school_id: int,
            session: AsyncSession,
     ) -> dict | None:
        """Return a single school by its user_id, or None if not found."""
        count_subq = (
            select(func.count(Student.id))
            .where(Student.school_id == School.user_id)
            .correlate(School)
            .scalar_subquery()
        )
    
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
        return {
            "user_id": user.id,
            "email": user.email,
            "name": user.name,
            "cnpj": school.cnpj,
            "is_private": school.is_private,
            "status": user.status.value,
            "created_at": user.created_at.isoformat(),
            "is_active": user.status == UserStatus.APROVADO,
            "quantidade_alunos": quantidade_alunos,
        }


