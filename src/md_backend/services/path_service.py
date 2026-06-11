"""Path (adaptive trail) service."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import (
    Content,
    Path,
    PathStatusEnum,
    StudentPathProgress,
    SubPath,
    SubPathItem,
    Subject,
)


class PathService:
    """Read-only operations for adaptive learning paths."""

    async def list_trails(
        self, session: AsyncSession, student_id: uuid.UUID
    ) -> list[dict]:
        """List all paths with per-student progress."""
        sub_path_count_sq = (
            select(SubPath.path_id, func.count(SubPath.id).label("total"))
            .group_by(SubPath.path_id)
            .subquery()
        )

        stmt = (
            select(Path, Content, Subject, sub_path_count_sq.c.total)
            .join(Content, Path.contents_id == Content.id)
            .join(Subject, Content.subject_id == Subject.id)
            .outerjoin(sub_path_count_sq, Path.id == sub_path_count_sq.c.path_id)
        )
        rows = (await session.execute(stmt)).all()

        progress_rows = (
            await session.execute(
                select(StudentPathProgress).where(
                    StudentPathProgress.student_id == student_id
                )
            )
        ).scalars().all()

        progress_by_path: dict[int, StudentPathProgress] = {
            p.path_id: p for p in progress_rows
        }

        result = []
        for path, content, subject, total_steps in rows:
            total = total_steps or 0
            progress_record = progress_by_path.get(path.id)

            if progress_record is None:
                completed = 0
                pct = 0
            elif progress_record.path_status == PathStatusEnum.COMPLETED:
                completed = total
                pct = 100
            else:
                completed = 0
                pct = 0

            result.append({
                "id": str(path.id),
                "name": path.name or content.name,
                "description": path.description or content.description,
                "subject": {
                    "id": str(subject.id),
                    "label": subject.name,
                    "color": subject.color,
                },
                "steps": total,
                "completed": completed,
                "progress": pct,
                "time_estimate": None,
            })

        return result

    async def get_trail_detail(
        self, session: AsyncSession, student_id: uuid.UUID, path_id: int
    ) -> dict | None:
        """Return full trail detail with sub-path statuses for a student."""
        row = (
            await session.execute(
                select(Path, Content, Subject)
                .join(Content, Path.contents_id == Content.id)
                .join(Subject, Content.subject_id == Subject.id)
                .where(Path.id == path_id)
            )
        ).one_or_none()

        if row is None:
            return None

        path, content, subject = row

        sub_paths = (
            await session.execute(
                select(SubPath).where(SubPath.path_id == path_id).order_by(SubPath.id)
            )
        ).scalars().all()

        progress = (
            await session.execute(
                select(StudentPathProgress).where(
                    StudentPathProgress.student_id == student_id,
                    StudentPathProgress.path_id == path_id,
                )
            )
        ).scalar_one_or_none()

        current_sub_path_id: int | None = (
            progress.current_sub_path if progress is not None else None
        )

        steps = []
        reached_current = False

        for order, sub_path in enumerate(sub_paths, start=1):
            if progress is None:
                if order == 1:
                    step_status = "available"
                else:
                    step_status = "locked"
            elif sub_path.id == current_sub_path_id:
                step_status = "available"
                reached_current = True
            elif not reached_current:
                step_status = "completed"
            else:
                step_status = "locked"

            items = (
                await session.execute(
                    select(SubPathItem)
                    .where(SubPathItem.sub_path_id == sub_path.id)
                    .order_by(SubPathItem.id)
                )
            ).scalars().all()

            sub_steps = [
                {
                    "id": str(item.id),
                    "kind": "question" if item.type_item == "exercise" else "resource",
                    "title": f"Etapa {item.id}",
                    "order": idx,
                    "status": step_status,
                    "questions": [],
                }
                for idx, item in enumerate(items, start=1)
            ]

            steps.append({
                "id": str(sub_path.id),
                "title": f"Etapa {order}",
                "description": None,
                "order": order,
                "status": step_status,
                "sub_steps": sub_steps,
            })

        total = len(steps)
        completed_count = sum(1 for s in steps if s["status"] == "completed")
        pct = round((completed_count / total) * 100) if total > 0 else 0

        return {
            "id": str(path.id),
            "title": path.name or content.name,
            "description": path.description or content.description,
            "subject": {
                "id": str(subject.id),
                "label": subject.name,
                "color": subject.color,
            },
            "progress": pct,
            "completed_steps": completed_count,
            "level_label": None,
            "time_estimate": None,
            "steps": steps,
        }
