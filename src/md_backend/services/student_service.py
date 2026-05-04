"""Student service for student registration."""

import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import (
    Attempt,
    ClassEnum,
    Content,
    StudentContentProgress,
    StudentProfile,
    Subject,
    Task,
    TaskStatusEnum,
    UserProfile,
    WellBeing,
)
from md_backend.utils.security import hash_password

_TASK_STATUS_TO_FRONTEND = {
    TaskStatusEnum.COMPLETED: "done",
    TaskStatusEnum.PENDING: "pending",
}


class StudentService:
    """Service for student operations."""

    async def create_student(
        self,
        first_name: str,
        last_name: str,
        email: str,
        password: str,
        birth_date: datetime.date,
        student_class: ClassEnum,
        session: AsyncSession,
        phone_number: str | None = None,
        school_id: uuid.UUID | None = None,
    ) -> dict | None:
        """Create a student atomically across user_profile and student_profile."""
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
            student_profile = StudentProfile(
                user=user_profile,
                birth_date=birth_date,
                student_class=student_class,
                school_id=school_id,
            )
            session.add(user_profile)
            session.add(student_profile)
            await session.commit()
            await session.refresh(user_profile)
            await session.refresh(student_profile)
        except IntegrityError:
            await session.rollback()
            return None

        return self._to_dict(user_profile, student_profile)

    async def get_students(
        self,
        session: AsyncSession,
        name: str | None = None,
        email: str | None = None,
        page: int = 1,
        size: int = 10,
    ) -> list[dict]:
        """List active students with optional filters and pagination."""
        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(UserProfile.is_active.is_(True))
        )

        if name:
            query = query.where(
                UserProfile.first_name.ilike(f"%{name}%") | UserProfile.last_name.ilike(f"%{name}%")
            )

        if email:
            query = query.where(UserProfile.email.ilike(f"%{email}%"))

        query = query.offset((page - 1) * size).limit(size)

        result = await session.execute(query)
        rows = result.all()

        return [self._to_dict(user, student) for user, student in rows]

    async def get_student_by_id(self, session: AsyncSession, student_id: uuid.UUID) -> dict | None:
        """Get a student by user_id."""
        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(
                StudentProfile.user_id == student_id,
                UserProfile.is_active.is_(True),
                StudentProfile.deactivated_at.is_(None),
            )
        )

        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return None

        user_profile, student_profile = row
        return self._to_dict(user_profile, student_profile)

    async def update_student(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        data: dict,
    ) -> dict | None:
        """Update a student's data. Returns None if not found."""
        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(StudentProfile.user_id == student_id)
        )
        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return None

        user_profile, student_profile = row

        user_fields = {"first_name", "last_name", "phone_number"}
        student_fields = {"birth_date", "student_class", "school_id"}

        for field, value in data.items():
            if value is None:
                continue
            if field in user_fields:
                setattr(user_profile, field, value)
            elif field in student_fields:
                setattr(student_profile, field, value)

        try:
            await session.commit()
            await session.refresh(user_profile)
            await session.refresh(student_profile)
        except Exception:
            await session.rollback()
            raise

        return self._to_dict(user_profile, student_profile)

    async def deactivate_student(self, session: AsyncSession, student_id: uuid.UUID) -> bool:
        """Soft delete a student by setting is_active to False."""
        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(StudentProfile.user_id == student_id)
        )
        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return False

        user_profile, student_profile = row
        now = datetime.datetime.now(datetime.UTC)
        user_profile.is_active = False
        user_profile.deactivated_at = now
        student_profile.deactivated_at = now

        await session.commit()
        return True

    async def get_summary_metrics(
        self, session: AsyncSession, student_id: uuid.UUID
    ) -> list[dict]:
        """Headline metrics for the student dashboard."""
        completed_tasks_q = select(func.count(Task.id)).where(
            Task.student_id == student_id,
            Task.task_status == TaskStatusEnum.COMPLETED,
            Task.deactivated_at.is_(None),
        )
        attempts_q = select(func.count(Attempt.id)).where(Attempt.student_id == student_id)
        mood_days_q = select(func.count(WellBeing.date)).where(
            WellBeing.student_id == student_id
        )

        completed_tasks = (await session.execute(completed_tasks_q)).scalar() or 0
        attempts = (await session.execute(attempts_q)).scalar() or 0
        mood_days = (await session.execute(mood_days_q)).scalar() or 0

        return [
            {"id": "completed-tasks", "title": "Tarefas Concluídas", "value": completed_tasks},
            {"id": "activities", "title": "Atividades Feitas", "value": attempts},
            {"id": "mood-days", "title": "Dias Registrados", "value": mood_days},
        ]

    async def get_disciplines_progress(
        self, session: AsyncSession, student_id: uuid.UUID
    ) -> list[dict]:
        """Average mastery (0-100) per subject for the given student."""
        query = (
            select(
                Subject.id,
                Subject.name,
                func.avg(StudentContentProgress.mastery_level).label("avg_mastery"),
            )
            .join(Content, Content.subject_id == Subject.id)
            .join(StudentContentProgress, StudentContentProgress.content_id == Content.id)
            .where(
                StudentContentProgress.student_id == student_id,
                StudentContentProgress.deactivated_at.is_(None),
            )
            .group_by(Subject.id, Subject.name)
            .order_by(Subject.name)
        )

        rows = (await session.execute(query)).all()
        return [self._discipline_to_dict(row) for row in rows]

    async def get_tasks(
        self, session: AsyncSession, student_id: uuid.UUID
    ) -> list[dict]:
        """All non-deactivated tasks for the student, newest first."""
        query = (
            select(Task)
            .where(Task.student_id == student_id, Task.deactivated_at.is_(None))
            .order_by(Task.date.desc())
        )
        tasks = (await session.execute(query)).scalars().all()
        return [self._task_to_dict(task) for task in tasks]

    def _to_dict(self, user_profile: UserProfile, student_profile: StudentProfile) -> dict:
        """Map user_profile and student_profile to a full response dict."""
        return {
            "id": str(student_profile.user_id),
            "user_id": str(user_profile.id),
            "first_name": user_profile.first_name,
            "last_name": user_profile.last_name,
            "email": user_profile.email,
            "phone_number": user_profile.phone_number or "",
            "birth_date": (
                student_profile.birth_date.isoformat() if student_profile.birth_date else ""
            ),
            "student_class": student_profile.student_class.value,
            "school_id": str(student_profile.school_id) if student_profile.school_id else "",
            "is_active": user_profile.is_active,
            "created_at": user_profile.created_at.isoformat() if user_profile.created_at else None,
        }

    def _discipline_to_dict(self, row) -> dict:
        """Map a (subject_id, name, avg_mastery) row to a discipline progress dict."""
        subject_id, name, avg_mastery = row
        return {
            "subjectId": str(subject_id),
            "subjectLabel": name,
            "progress": int(round(float(avg_mastery or 0) * 100)),
        }

    def _task_to_dict(self, task: Task) -> dict:
        """Map a Task row to the response dict expected by the dashboard."""
        task_status = task.task_status
        return {
            "id": str(task.id),
            "title": task.description,
            "date": task.date.isoformat() if task.date else None,
            "status": (
                _TASK_STATUS_TO_FRONTEND.get(task_status, "pending")
                if task_status is not None
                else "pending"
            ),
            "subject": {"label": ""},
        }
