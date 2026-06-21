"""Content service."""

import math

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import (
    Attempt,
    Content,
    Exercise,
    Option,
    Path,
    PathTransition,
    Resource,
    StudentContentProgress,
    StudentPathProgress,
    StudentSubPathItemProgress,
    Subject,
    SubPath,
    SubPathItem,
)


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
        """Delete a content record and trail/resource structures that depend on it."""
        content = await session.get(Content, content_id)
        if content is None:
            return False

        path_ids = set(
            (await session.execute(select(Path.id).where(Path.content_id == content_id)))
            .scalars()
            .all()
        )
        path_ids.update(
            (await session.execute(select(SubPath.path_id).where(SubPath.content_id == content_id)))
            .scalars()
            .all()
        )
        if path_ids:
            sub_path_ids = (
                (await session.execute(select(SubPath.id).where(SubPath.path_id.in_(path_ids))))
                .scalars()
                .all()
            )
            await session.execute(
                delete(StudentSubPathItemProgress).where(
                    StudentSubPathItemProgress.path_id.in_(path_ids)
                )
            )
            await session.execute(
                delete(StudentPathProgress).where(StudentPathProgress.path_id.in_(path_ids))
            )
            if sub_path_ids:
                await session.execute(
                    delete(PathTransition).where(
                        or_(
                            PathTransition.sub_path_origin_id.in_(sub_path_ids),
                            PathTransition.sub_path_destination_id.in_(sub_path_ids),
                        )
                    )
                )
                await session.execute(
                    delete(SubPathItem).where(SubPathItem.sub_path_id.in_(sub_path_ids))
                )
                await session.execute(delete(SubPath).where(SubPath.path_id.in_(path_ids)))
            await session.execute(delete(Path).where(Path.id.in_(path_ids)))

        resource_ids = (
            (await session.execute(select(Resource.id).where(Resource.content_id == content_id)))
            .scalars()
            .all()
        )
        if resource_ids:
            resource_item_ids = (
                (
                    await session.execute(
                        select(SubPathItem.id).where(SubPathItem.resource_id.in_(resource_ids))
                    )
                )
                .scalars()
                .all()
            )
            if resource_item_ids:
                await session.execute(
                    delete(StudentSubPathItemProgress).where(
                        StudentSubPathItemProgress.sub_path_item_id.in_(resource_item_ids)
                    )
                )
                await session.execute(
                    delete(SubPathItem).where(SubPathItem.id.in_(resource_item_ids))
                )
            await session.execute(delete(Resource).where(Resource.id.in_(resource_ids)))

        exercise_ids = (
            (await session.execute(select(Exercise.id).where(Exercise.content_id == content_id)))
            .scalars()
            .all()
        )
        if exercise_ids:
            exercise_item_ids = (
                (
                    await session.execute(
                        select(SubPathItem.id).where(SubPathItem.exercise_id.in_(exercise_ids))
                    )
                )
                .scalars()
                .all()
            )
            if exercise_item_ids:
                await session.execute(
                    delete(StudentSubPathItemProgress).where(
                        StudentSubPathItemProgress.sub_path_item_id.in_(exercise_item_ids)
                    )
                )
                await session.execute(
                    delete(SubPathItem).where(SubPathItem.id.in_(exercise_item_ids))
                )
            await session.execute(delete(Attempt).where(Attempt.exercise_id.in_(exercise_ids)))
            await session.execute(delete(Option).where(Option.exercise_id.in_(exercise_ids)))
            await session.execute(delete(Exercise).where(Exercise.id.in_(exercise_ids)))

        await session.execute(
            delete(StudentContentProgress).where(StudentContentProgress.content_id == content_id)
        )
        await session.delete(content)
        await session.commit()
        return True


def _serialize(content: Content, subject: Subject) -> dict:
    return {
        "id": str(content.id),
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
