"""Content service."""

import math

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import Content, Subject


class ContentService:
    """CRUD operations for content records."""

    async def list_contents(
        self,
        session: AsyncSession,
        page: int = 1,
        page_size: int = 10,
        query: str | None = None,
    ) -> dict:
        """List content records joined with their subject."""
        stmt = select(Content, Subject).join(Subject, Content.subject_id == Subject.id)
        if query:
            pattern = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                func.lower(Content.name).like(pattern) | func.lower(Subject.name).like(pattern)
            )

        total = (
            await session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        stmt = stmt.order_by(Content.id.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await session.execute(stmt)).all()

        return {
            "items": [_serialize(content, subject) for content, subject in rows],
            "page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": max(1, math.ceil(total / page_size)) if total else 1,
        }

    async def get_content(self, session: AsyncSession, content_id: int) -> dict | None:
        """Fetch a single content record."""
        row = (
            await session.execute(
                select(Content, Subject)
                .join(Subject, Content.subject_id == Subject.id)
                .where(Content.id == content_id)
            )
        ).one_or_none()
        if row is None:
            return None
        content, subject = row
        return _serialize(content, subject)

    async def create_content(
        self,
        session: AsyncSession,
        subject_id: int,
        title: str,
        description: str | None = None,
    ) -> dict | None:
        """Create a content record. Returns None when the subject does not exist."""
        subject = await session.get(Subject, subject_id)
        if subject is None:
            return None

        content = Content(subject_id=subject_id, name=title.strip(), description=description)
        session.add(content)
        await session.commit()
        await session.refresh(content)
        return _serialize(content, subject)

    async def update_content(
        self,
        session: AsyncSession,
        content_id: int,
        subject_id: int,
        title: str,
        description: str | None = None,
    ) -> dict | None:
        """Update a content record. Returns None when content or subject is missing."""
        content = await session.get(Content, content_id)
        if content is None:
            return None
        subject = await session.get(Subject, subject_id)
        if subject is None:
            return None

        content.subject_id = subject_id
        content.name = title.strip()
        content.description = description
        await session.commit()
        await session.refresh(content)
        return _serialize(content, subject)

    async def delete_content(self, session: AsyncSession, content_id: int) -> bool:
        """Delete a content record."""
        content = await session.get(Content, content_id)
        if content is None:
            return False
        await session.delete(content)
        await session.commit()
        return True


def _serialize(content: Content, subject: Subject) -> dict:
    return {
        "id": content.id,
        "title": content.name,
        "description": content.description,
        "created_at": content.created_at.isoformat() if content.created_at else None,
        "updated_at": content.updated_at.isoformat() if content.updated_at else None,
        "subject": {
            "id": str(subject.id),
            "name": subject.name,
            "slug": subject.slug,
            "color": subject.color,
        },
    }
