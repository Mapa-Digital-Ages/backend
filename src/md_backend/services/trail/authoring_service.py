"""Trail authoring service for assembling paths from existing content."""

import json
from collections.abc import Sequence

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import StructuredTrailStepRequest, StructuredTrailSubStepRequest
from md_backend.models.db_models import (
    Content,
    DifficultyEnum,
    Exercise,
    Path,
    PathTransition,
    Resource,
    ResourceTypeEnum,
    RuleTypeEnum,
    StudentPathProgress,
    StudentSubPathItemProgress,
    Subject,
    SubPath,
    SubPathItem,
    TypeItemEnum,
)
from md_backend.services.trail.generation_service import ContentGenerationService

_DIFFICULTY_MAP = {1: DifficultyEnum.EASY, 2: DifficultyEnum.MEDIUM, 3: DifficultyEnum.HARD}
_NUMERIC_DIFFICULTY = {
    DifficultyEnum.VERY_EASY: 1,
    DifficultyEnum.EASY: 1,
    DifficultyEnum.MEDIUM: 2,
    DifficultyEnum.HARD: 3,
    DifficultyEnum.VERY_HARD: 3,
}


class TrailAuthoringService:
    """Create trail catalog records from existing content bank rows."""

    def _eixo_from_path(self, path: Path) -> list[str]:
        """Deserialize stored trail axes."""
        if not path.eixo:
            return []
        try:
            parsed = json.loads(path.eixo)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [item for item in parsed if isinstance(item, str) and item.strip()]

    def _store_eixo(self, eixo: list[str]) -> str:
        """Serialize trail axes without losing Portuguese characters."""
        return json.dumps(eixo, ensure_ascii=False)

    def _serialize_path(
        self,
        path: Path,
        content: Content,
        subject: Subject,
        question_count: int,
        steps: list[dict],
    ) -> dict:
        return {
            "id": path.id,
            "title": path.name or content.name,
            "name": path.name or content.name,
            "description": path.description or "",
            "content_id": content.id,
            "content_title": content.name,
            "subject_id": str(subject.id),
            "subject": {
                "id": str(subject.id),
                "name": subject.name,
                "color": subject.color,
            },
            "eixo": self._eixo_from_path(path),
            "steps": steps,
            "step_count": len(steps),
            "question_count": int(question_count or 0),
        }

    async def _serialize_steps(self, session: AsyncSession, path_id: int) -> list[dict]:
        """Serialize sub-paths into the admin step shape."""
        sub_paths = (
            (
                await session.execute(
                    select(SubPath)
                    .where(SubPath.path_id == path_id)
                    .order_by(SubPath.order, SubPath.id)
                )
            )
            .scalars()
            .all()
        )

        steps: list[dict] = []
        for index, sub_path in enumerate(sub_paths, start=1):
            items = (
                (
                    await session.execute(
                        select(SubPathItem)
                        .where(SubPathItem.sub_path_id == sub_path.id)
                        .order_by(SubPathItem.order, SubPathItem.id)
                    )
                )
                .scalars()
                .all()
            )
            content_id: int | None = sub_path.content_id
            content_title: str | None = None
            title = sub_path.title or f"Etapa {index}"
            description = sub_path.description or ""

            if content_id is not None:
                content = await session.get(Content, content_id)
                content_title = content.name if content is not None else None

            difficulty = (
                _NUMERIC_DIFFICULTY.get(sub_path.difficulty) if sub_path.difficulty else None
            )
            sub_steps = await self._serialize_sub_steps(session=session, items=items)
            first_sub_step = sub_steps[0] if sub_steps else None
            steps.append(
                {
                    "id": str(sub_path.id),
                    "order": sub_path.order or index,
                    "title": title,
                    "description": description,
                    "contentId": str(
                        content_id or first_sub_step.get("contentId", "") if first_sub_step else ""
                    ),
                    "contentTitle": content_title
                    or (first_sub_step.get("contentTitle") if first_sub_step else None),
                    "activityType": first_sub_step.get("activityType")
                    if first_sub_step
                    else "text",
                    "questionCount": first_sub_step.get("questionCount")
                    if first_sub_step
                    else None,
                    "difficulty": first_sub_step.get("difficulty") or difficulty
                    if first_sub_step
                    else difficulty,
                    "subSteps": sub_steps,
                }
            )
        return steps

    async def _serialize_sub_steps(
        self,
        session: AsyncSession,
        items: Sequence[SubPathItem],
    ) -> list[dict]:
        """Serialize sub-path items as editable admin sub-steps."""
        grouped: dict[str, list[SubPathItem]] = {}
        order: list[str] = []
        for item in items:
            group_key = item.group_key or f"item-{item.id}"
            if group_key not in grouped:
                grouped[group_key] = []
                order.append(group_key)
            grouped[group_key].append(item)

        sub_steps: list[dict] = []
        for index, group_key in enumerate(order, start=1):
            group_items = grouped[group_key]
            first = group_items[0]
            if first.type_item == TypeItemEnum.EXERCISE:
                exercise = await session.get(Exercise, first.exercise_id)
                content = await session.get(Content, exercise.content_id) if exercise else None
                difficulty = (
                    _NUMERIC_DIFFICULTY.get(exercise.difficulty)
                    if exercise and exercise.difficulty
                    else None
                )
                sub_steps.append(
                    {
                        "id": group_key,
                        "order": index,
                        "title": first.title or f"Questionário {index}",
                        "description": first.description or "",
                        "contentId": str(exercise.content_id if exercise else ""),
                        "contentTitle": content.name if content is not None else None,
                        "activityType": "question",
                        "questionCount": len(group_items),
                        "difficulty": difficulty,
                    }
                )
                continue

            resource = await session.get(Resource, first.resource_id)
            content = await session.get(Content, resource.content_id) if resource else None
            activity_type = (
                "video" if resource and resource.type == ResourceTypeEnum.VIDEO else "text"
            )
            sub_steps.append(
                {
                    "id": group_key,
                    "order": index,
                    "title": first.title or (resource.title if resource else f"Material {index}"),
                    "description": first.description or "",
                    "contentId": str(resource.content_id if resource else ""),
                    "contentTitle": content.name if content is not None else None,
                    "activityType": activity_type,
                    "questionCount": None,
                    "difficulty": None,
                }
            )
        return sub_steps

    async def list_paths(
        self,
        session: AsyncSession,
        *,
        page: int = 1,
        page_size: int = 10,
        query: str | None = None,
        subject_id: int | None = None,
    ) -> dict:
        """List authored adaptive trails for admin management."""
        question_count = func.count(SubPathItem.id).label("question_count")
        filters = []
        normalized_query = (query or "").strip()
        if normalized_query:
            search = f"%{normalized_query}%"
            filters.append(
                or_(
                    Path.name.ilike(search),
                    Path.description.ilike(search),
                    Content.name.ilike(search),
                    Content.description.ilike(search),
                    Subject.name.ilike(search),
                )
            )
        if subject_id is not None:
            filters.append(Subject.id == subject_id)

        base = (
            select(Path, Content, Subject, question_count)
            .join(Content, Content.id == Path.content_id)
            .join(Subject, Subject.id == Content.subject_id)
            .outerjoin(SubPath, SubPath.path_id == Path.id)
            .outerjoin(
                SubPathItem,
                (SubPathItem.sub_path_id == SubPath.id)
                & (SubPathItem.type_item == TypeItemEnum.EXERCISE),
            )
            .where(*filters)
            .group_by(Path.id, Content.id, Subject.id)
        )
        total_items = (
            await session.execute(
                select(func.count()).select_from(
                    select(Path.id)
                    .join(Content, Content.id == Path.content_id)
                    .join(Subject, Subject.id == Content.subject_id)
                    .where(*filters)
                    .subquery()
                )
            )
        ).scalar_one()
        safe_page_size = max(1, min(page_size, 100))
        total_pages = max(1, (total_items + safe_page_size - 1) // safe_page_size)
        safe_page = max(1, min(page, total_pages))
        rows = (
            await session.execute(
                base.order_by(Path.id.desc())
                .offset((safe_page - 1) * safe_page_size)
                .limit(safe_page_size)
            )
        ).all()

        items = []
        for path, content, subject, total in rows:
            steps = await self._serialize_steps(session=session, path_id=path.id)
            items.append(self._serialize_path(path, content, subject, total, steps))

        return {
            "items": items,
            "page": safe_page,
            "page_size": safe_page_size,
            "total_items": total_items,
            "total_pages": total_pages,
        }

    async def update_path(
        self,
        session: AsyncSession,
        path_id: int,
        content_id: int | None,
        name: str,
        description: str | None,
    ) -> dict | None:
        """Update trail metadata."""
        path = (await session.execute(select(Path).where(Path.id == path_id))).scalar_one_or_none()
        if path is None:
            return None
        if content_id is not None:
            content_exists = (
                await session.execute(select(Content.id).where(Content.id == content_id))
            ).scalar_one_or_none()
            if content_exists is None:
                raise LookupError("content not found")
            path.content_id = content_id
        path.name = name
        path.description = description
        await session.commit()

        row = (
            await session.execute(
                select(Path, Content, Subject, func.count(SubPathItem.id))
                .join(Content, Content.id == Path.content_id)
                .join(Subject, Subject.id == Content.subject_id)
                .outerjoin(SubPath, SubPath.path_id == Path.id)
                .outerjoin(
                    SubPathItem,
                    (SubPathItem.sub_path_id == SubPath.id)
                    & (SubPathItem.type_item == TypeItemEnum.EXERCISE),
                )
                .where(Path.id == path_id)
                .group_by(Path.id, Content.id, Subject.id)
            )
        ).one_or_none()
        if row is None:
            return None

        updated_path, content, subject, question_count = row
        steps = await self._serialize_steps(session=session, path_id=updated_path.id)
        return self._serialize_path(updated_path, content, subject, question_count, steps)

    async def delete_path(self, session: AsyncSession, path_id: int) -> bool:
        """Delete a trail path and its trail-specific structure."""
        path = (await session.execute(select(Path).where(Path.id == path_id))).scalar_one_or_none()
        if path is None:
            return False

        sub_path_ids = (
            (await session.execute(select(SubPath.id).where(SubPath.path_id == path_id)))
            .scalars()
            .all()
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
                delete(StudentSubPathItemProgress).where(
                    StudentSubPathItemProgress.path_id == path_id
                )
            )
            await session.execute(
                delete(StudentPathProgress).where(StudentPathProgress.path_id == path_id)
            )
            await session.execute(
                delete(SubPathItem).where(SubPathItem.sub_path_id.in_(sub_path_ids))
            )
            await session.execute(delete(SubPath).where(SubPath.path_id == path_id))
        else:
            await session.execute(
                delete(StudentPathProgress).where(StudentPathProgress.path_id == path_id)
            )
        await session.delete(path)
        await session.commit()
        return True

    async def create_path(
        self,
        session: AsyncSession,
        content_id: int,
        name: str | None,
        description: str | None,
    ) -> int:
        """Create a path for existing content."""
        content = (
            await session.execute(select(Content).where(Content.id == content_id))
        ).scalar_one_or_none()
        if content is None:
            raise LookupError("content not found")
        path = Path(content_id=content_id, name=name, description=description)
        session.add(path)
        await session.commit()
        return path.id

    async def add_sub_path(
        self,
        session: AsyncSession,
        path_id: int,
        difficulty: DifficultyEnum | None,
        order: int,
        content_id: int | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> int:
        """Add a sub-path to an existing path."""
        path = (await session.execute(select(Path).where(Path.id == path_id))).scalar_one_or_none()
        if path is None:
            raise LookupError("path not found")
        sub_path = SubPath(
            path_id=path_id,
            content_id=content_id,
            title=title,
            description=description,
            difficulty=difficulty,
            order=order,
        )
        session.add(sub_path)
        await session.commit()
        return sub_path.id

    async def add_item(
        self,
        session: AsyncSession,
        sub_path_id: int,
        type_item: TypeItemEnum,
        resource_id: int | None,
        exercise_id: int | None,
        order: int,
        group_key: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> int:
        """Add an existing resource or exercise sub-step item to a sub-path."""
        sub_path = (
            await session.execute(select(SubPath).where(SubPath.id == sub_path_id))
        ).scalar_one_or_none()
        if sub_path is None:
            raise LookupError("sub-path not found")

        if type_item == TypeItemEnum.EXERCISE:
            target = (
                await session.execute(select(Exercise.id).where(Exercise.id == exercise_id))
            ).scalar_one_or_none()
        else:
            target = (
                await session.execute(select(Resource.id).where(Resource.id == resource_id))
            ).scalar_one_or_none()
        if target is None:
            raise LookupError("target content not found")

        item = SubPathItem(
            sub_path_id=sub_path_id,
            type_item=type_item,
            resource_id=resource_id,
            exercise_id=exercise_id,
            order=order,
            group_key=group_key,
            title=title,
            description=description,
        )
        session.add(item)
        await session.commit()
        return item.id

    async def _validate_structured_contents(
        self,
        session: AsyncSession,
        subject_id: int,
        steps: Sequence[StructuredTrailStepRequest],
    ) -> None:
        """Ensure the selected subject and step contents exist and match."""
        subject = await session.get(Subject, subject_id)
        if subject is None:
            raise LookupError("subject not found")

        content_ids = {sub_step.content_id for step in steps for sub_step in (step.sub_steps or [])}
        rows = (
            (await session.execute(select(Content).where(Content.id.in_(content_ids))))
            .scalars()
            .all()
        )
        content_by_id = {content.id: content for content in rows}
        if len(content_by_id) != len(content_ids):
            raise LookupError("content not found")
        if any(content.subject_id != subject_id for content in content_by_id.values()):
            raise ValueError("all step contents must belong to the selected subject")

    async def _resource_id_for_step(
        self,
        session: AsyncSession,
        *,
        content_id: int,
        activity_type: str,
        title: str,
        order: int,
    ) -> int:
        """Return an existing related resource or create a lightweight text placeholder."""
        stmt = select(Resource).where(Resource.content_id == content_id)
        if activity_type == "video":
            stmt = stmt.where(Resource.type == ResourceTypeEnum.VIDEO)
        else:
            stmt = stmt.where(Resource.type != ResourceTypeEnum.VIDEO)

        resource = (await session.execute(stmt.order_by(Resource.id))).scalar_one_or_none()
        if resource is not None:
            return resource.id

        placeholder = Resource(
            content_id=content_id,
            type=ResourceTypeEnum.LINK,
            title=title or f"Material da etapa {order}",
            file_url=f"about:blank#trail-step-{order}",
        )
        session.add(placeholder)
        await session.flush()
        return placeholder.id

    async def _clear_path_structure(self, session: AsyncSession, path_id: int) -> None:
        """Remove trail-specific structure before replacing it."""
        sub_path_ids = (
            (await session.execute(select(SubPath.id).where(SubPath.path_id == path_id)))
            .scalars()
            .all()
        )
        if not sub_path_ids:
            return

        await session.execute(
            delete(StudentPathProgress).where(StudentPathProgress.path_id == path_id)
        )
        await session.execute(
            delete(PathTransition).where(
                or_(
                    PathTransition.sub_path_origin_id.in_(sub_path_ids),
                    PathTransition.sub_path_destination_id.in_(sub_path_ids),
                )
            )
        )
        await session.execute(
            delete(StudentSubPathItemProgress).where(StudentSubPathItemProgress.path_id == path_id)
        )
        await session.execute(delete(SubPathItem).where(SubPathItem.sub_path_id.in_(sub_path_ids)))
        await session.execute(delete(SubPath).where(SubPath.path_id == path_id))

    async def _add_structured_steps(
        self,
        session: AsyncSession,
        *,
        path_id: int,
        eixo: list[str],
        steps: Sequence[StructuredTrailStepRequest],
        generation_service: ContentGenerationService,
    ) -> dict:
        """Persist all sub-paths and items for a structured trail."""
        sub_path_ids: list[int] = []
        exercise_ids: list[int] = []
        item_ids: list[int] = []

        for index, step in enumerate(sorted(steps, key=lambda item: item.order), start=1):
            sub_steps = sorted(step.sub_steps or [], key=lambda item: item.order)
            first_question = next(
                (sub_step for sub_step in sub_steps if sub_step.activity.type == "question"),
                None,
            )
            difficulty = (
                _DIFFICULTY_MAP.get(first_question.activity.difficulty or 1)
                if first_question
                else None
            )
            first_content_id = sub_steps[0].content_id if sub_steps else None
            sub_path_id = await self.add_sub_path(
                session=session,
                path_id=path_id,
                difficulty=difficulty,
                order=step.order or index,
                content_id=first_content_id,
                title=step.title,
                description=step.description,
            )
            sub_path_ids.append(sub_path_id)

            for sub_step_index, sub_step in enumerate(sub_steps, start=1):
                group_key = f"{sub_path_id}-{sub_step_index}"
                if sub_step.activity.type == "question":
                    created = await self._add_question_sub_step(
                        session=session,
                        generation_service=generation_service,
                        sub_path_id=sub_path_id,
                        sub_step=sub_step,
                        eixo=eixo,
                        group_key=group_key,
                    )
                    item_ids.extend(created["item_ids"])
                    exercise_ids.extend(created["exercise_ids"])
                    continue

                item_id = await self._add_resource_sub_step(
                    session=session,
                    sub_path_id=sub_path_id,
                    sub_step=sub_step,
                    group_key=group_key,
                )
                item_ids.append(item_id)

        return {
            "sub_path_ids": sub_path_ids,
            "exercise_ids": exercise_ids,
            "item_ids": item_ids,
        }

    async def _add_question_sub_step(
        self,
        session: AsyncSession,
        *,
        generation_service: ContentGenerationService,
        sub_path_id: int,
        sub_step: StructuredTrailSubStepRequest,
        eixo: list[str],
        group_key: str,
    ) -> dict:
        """Generate and persist a question sub-step."""
        generated = await generation_service.generate_for_content(
            session=session,
            content_id=sub_step.content_id,
            eixo=eixo,
            count=sub_step.activity.question_count or 5,
            difficulty=sub_step.activity.difficulty or 1,
        )
        item_ids: list[int] = []
        for item_order, exercise_id in enumerate(
            generated["created_exercise_ids"],
            start=1,
        ):
            item_ids.append(
                await self.add_item(
                    session=session,
                    sub_path_id=sub_path_id,
                    type_item=TypeItemEnum.EXERCISE,
                    resource_id=None,
                    exercise_id=exercise_id,
                    order=item_order,
                    group_key=group_key,
                    title=sub_step.title,
                    description=sub_step.description,
                )
            )
        return {"exercise_ids": generated["created_exercise_ids"], "item_ids": item_ids}

    async def _add_resource_sub_step(
        self,
        session: AsyncSession,
        *,
        sub_path_id: int,
        sub_step: StructuredTrailSubStepRequest,
        group_key: str,
    ) -> int:
        """Persist a text or video resource sub-step."""
        resource_id = await self._resource_id_for_step(
            session=session,
            content_id=sub_step.content_id,
            activity_type=sub_step.activity.type,
            title=sub_step.title,
            order=sub_step.order,
        )
        return await self.add_item(
            session=session,
            sub_path_id=sub_path_id,
            type_item=TypeItemEnum.RESOURCE,
            resource_id=resource_id,
            exercise_id=None,
            order=1,
            group_key=group_key,
            title=sub_step.title,
            description=sub_step.description,
        )

    async def create_structured_path(
        self,
        session: AsyncSession,
        *,
        title: str,
        description: str | None,
        subject_id: int,
        eixo: list[str],
        steps: Sequence[StructuredTrailStepRequest],
        generation_service: ContentGenerationService,
    ) -> dict:
        """Create a full adaptive trail from multiple content-backed steps."""
        await self._validate_structured_contents(
            session=session,
            subject_id=subject_id,
            steps=steps,
        )
        first_step = sorted(steps, key=lambda item: item.order)[0]
        first_content_id = sorted(first_step.sub_steps or [], key=lambda item: item.order)[
            0
        ].content_id
        path_id = await self.create_path(
            session=session,
            content_id=first_content_id,
            name=title,
            description=description,
        )
        path = await session.get(Path, path_id)
        if path is not None:
            path.eixo = self._store_eixo(eixo)
            await session.commit()
        result = await self._add_structured_steps(
            session=session,
            path_id=path_id,
            eixo=eixo,
            steps=steps,
            generation_service=generation_service,
        )
        return {"path_id": path_id, **result}

    async def replace_structured_path(
        self,
        session: AsyncSession,
        *,
        path_id: int,
        title: str,
        description: str | None,
        subject_id: int,
        eixo: list[str],
        steps: Sequence[StructuredTrailStepRequest],
        generation_service: ContentGenerationService,
    ) -> dict | None:
        """Replace a trail's editable structure and reset invalidated progress."""
        path = (await session.execute(select(Path).where(Path.id == path_id))).scalar_one_or_none()
        if path is None:
            return None

        await self._validate_structured_contents(
            session=session,
            subject_id=subject_id,
            steps=steps,
        )
        first_step = sorted(steps, key=lambda item: item.order)[0]
        first_content_id = sorted(first_step.sub_steps or [], key=lambda item: item.order)[
            0
        ].content_id
        path.content_id = first_content_id
        path.name = title
        path.description = description
        path.eixo = self._store_eixo(eixo)
        await self._clear_path_structure(session=session, path_id=path_id)
        await session.commit()

        result = await self._add_structured_steps(
            session=session,
            path_id=path_id,
            eixo=eixo,
            steps=steps,
            generation_service=generation_service,
        )
        return {"path_id": path_id, **result}

    async def add_transition(
        self,
        session: AsyncSession,
        origin_id: int,
        destination_id: int,
        rule_type: RuleTypeEnum,
        rule_value: int | None,
    ) -> int:
        """Add an adaptive transition between sub-paths in the same path."""
        rows = (
            await session.execute(
                select(SubPath.id, SubPath.path_id).where(
                    SubPath.id.in_([origin_id, destination_id])
                )
            )
        ).all()
        path_ids = {path_id for _, path_id in rows}
        if len(rows) != 2 or len(path_ids) != 1:
            raise ValueError("origin and destination must be sub-paths in the same path")

        transition = PathTransition(
            sub_path_origin_id=origin_id,
            sub_path_destination_id=destination_id,
            rule_type=rule_type,
            rule_value=rule_value,
        )
        session.add(transition)
        await session.commit()
        return transition.id
