"""Trail authoring service for assembling paths from existing content."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import (
    Content,
    DifficultyEnum,
    Exercise,
    Path,
    PathTransition,
    Resource,
    RuleTypeEnum,
    SubPath,
    SubPathItem,
    TypeItemEnum,
)


class TrailAuthoringService:
    """Create trail catalog records from existing content bank rows."""

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
    ) -> int:
        """Add a sub-path to an existing path."""
        path = (await session.execute(select(Path).where(Path.id == path_id))).scalar_one_or_none()
        if path is None:
            raise LookupError("path not found")
        sub_path = SubPath(path_id=path_id, difficulty=difficulty, order=order)
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
    ) -> int:
        """Add an existing resource or exercise to a sub-path."""
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
        )
        session.add(item)
        await session.commit()
        return item.id

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
