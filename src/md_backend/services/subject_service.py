"""Subject service."""

import unicodedata

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import Content, StudentUpload, Subject, Task

DEFAULT_SUBJECTS = (
    {"slug": "biology", "name": "Biologia", "color": "rgba(20, 184, 166, 1)"},
    {"slug": "english", "name": "Inglês", "color": "rgba(254, 51, 163, 1)"},
    {"slug": "geography", "name": "Geografia", "color": "rgba(0, 212, 106, 1)"},
    {"slug": "history", "name": "História", "color": "rgba(255, 186, 0, 1)"},
    {"slug": "mathematics", "name": "Matemática", "color": "rgba(173, 68, 248, 1)"},
    {"slug": "portuguese", "name": "Português", "color": "rgba(5, 113, 247, 1)"},
    {"slug": "science", "name": "Ciências", "color": "rgba(0, 210, 237, 1)"},
)


async def seed_default_subjects(session: AsyncSession) -> int:
    """Insert the default subject catalog. Returns the number of subjects created."""
    existing = (await session.execute(select(Subject.name))).scalars().all()
    existing_lower = {name.casefold() for name in existing}

    created = 0
    for data in DEFAULT_SUBJECTS:
        if data["name"].casefold() in existing_lower:
            continue
        session.add(Subject(name=data["name"], slug=data["slug"], color=data["color"]))
        created += 1
    return created


def _slugify(value: str) -> str:
    """Build a stable ASCII slug from a display name."""
    normalized = unicodedata.normalize("NFD", value.strip())
    ascii_value = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in ascii_value)
    return "-".join(part for part in slug.split("-") if part) or "subject"


def _to_dict(
    subject: Subject,
    content_count: int,
    tasks_count: int,
    uploads_count: int,
) -> dict:
    total = int(content_count) + int(tasks_count) + int(uploads_count)
    return {
        "id": str(subject.id),
        "slug": subject.slug,
        "name": subject.name,
        "color": subject.color,
        "content_count": int(content_count),
        "tasks_count": int(tasks_count),
        "uploads_count": int(uploads_count),
        "references_count": total,
    }


class SubjectService:
    """Subject catalog operations."""

    async def list_subjects(self, session: AsyncSession) -> list[dict]:
        """List subjects with content, task, and upload counts."""
        rows = (await session.execute(self._stats_query())).all()
        return sorted(
            (
                _to_dict(subject, content_total, task_total, upload_total)
                for subject, content_total, task_total, upload_total in rows
            ),
            key=lambda s: s["name"],
        )

    async def get_subject(self, session: AsyncSession, subject_id: int) -> dict | None:
        """Fetch a subject with its reference counts."""
        row = (
            await session.execute(self._stats_query().where(Subject.id == subject_id))
        ).one_or_none()
        if row is None:
            return None
        subject, content_total, task_total, upload_total = row
        return _to_dict(subject, content_total, task_total, upload_total)

    async def update_subject(
        self,
        session: AsyncSession,
        subject_id: int,
        name: str | None = None,
        color: str | None = None,
    ) -> dict | None | str:
        """Update a subject's name and/or color. Returns 'name_conflict' if taken."""
        subject = await session.get(Subject, subject_id)
        if subject is None:
            return None

        if name is not None:
            normalized = name.strip()
            if normalized.lower() != subject.name.lower():
                clash = await session.execute(
                    select(Subject).where(
                        func.lower(Subject.name) == normalized.lower(),
                        Subject.id != subject_id,
                    )
                )
                if clash.scalar_one_or_none() is not None:
                    return "name_conflict"
                subject.name = normalized
                subject.slug = _slugify(normalized)

        if color is not None:
            subject.color = color

        await session.commit()
        await session.refresh(subject)
        return await self.get_subject(session, subject_id)

    async def create_subject(
        self, session: AsyncSession, name: str, color: str | None = None
    ) -> dict | None:
        """Create a subject; returns None when the name already exists."""
        normalized = name.strip()
        existing = await session.execute(
            select(Subject).where(func.lower(Subject.name) == normalized.lower())
        )
        if existing.scalar_one_or_none() is not None:
            return None

        subject = Subject(
            name=normalized,
            slug=_slugify(normalized),
            color=color or "rgba(32, 109, 197, 1)",
        )
        session.add(subject)
        await session.commit()
        await session.refresh(subject)
        return _to_dict(subject, 0, 0, 0)

    async def delete_subject(self, session: AsyncSession, subject_id: int) -> str:
        """Delete a subject when nothing references it."""
        subject = await session.get(Subject, subject_id)
        if subject is None:
            return "not_found"

        content_refs = (
            await session.execute(
                select(func.count(Content.id)).where(Content.subject_id == subject_id)
            )
        ).scalar() or 0
        task_refs = (
            await session.execute(select(func.count(Task.id)).where(Task.subject_id == subject_id))
        ).scalar() or 0
        upload_refs = (
            await session.execute(
                select(func.count(StudentUpload.id)).where(StudentUpload.subject_id == subject_id)
            )
        ).scalar() or 0
        if content_refs + task_refs + upload_refs > 0:
            return "has_references"

        await session.delete(subject)
        await session.commit()
        return "deleted"

    def _stats_query(self):
        content_count = (
            select(Content.subject_id, func.count(Content.id).label("total"))
            .group_by(Content.subject_id)
            .subquery()
        )
        task_count = (
            select(Task.subject_id, func.count(Task.id).label("total"))
            .where(Task.deactivated_at.is_(None))
            .group_by(Task.subject_id)
            .subquery()
        )
        upload_count = (
            select(StudentUpload.subject_id, func.count(StudentUpload.id).label("total"))
            .where(StudentUpload.subject_id.is_not(None))
            .group_by(StudentUpload.subject_id)
            .subquery()
        )
        return (
            select(
                Subject,
                func.coalesce(content_count.c.total, 0),
                func.coalesce(task_count.c.total, 0),
                func.coalesce(upload_count.c.total, 0),
            )
            .outerjoin(content_count, content_count.c.subject_id == Subject.id)
            .outerjoin(task_count, task_count.c.subject_id == Subject.id)
            .outerjoin(upload_count, upload_count.c.subject_id == Subject.id)
        )
