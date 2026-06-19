"""Integration tests for TrailAuthoringService."""

import unittest
import uuid

from md_backend.models.db_models import (
    Content,
    DifficultyEnum,
    Exercise,
    Path,
    Resource,
    ResourceTypeEnum,
    RuleTypeEnum,
    Subject,
    SubPath,
    TypeItemEnum,
)
from md_backend.services.trail.authoring_service import TrailAuthoringService
from md_backend.utils.database import AsyncSessionLocal, init_db


class TestTrailAuthoringService(unittest.IsolatedAsyncioTestCase):
    """Authoring service persists and validates trail catalog records."""

    async def asyncSetUp(self):
        await init_db()
        self.service = TrailAuthoringService()

    async def _seed_content(self, session):
        suffix = uuid.uuid4().hex[:8]
        subject = Subject(name=f"Authoring {suffix}", slug=f"authoring-{suffix}", color="#000")
        session.add(subject)
        await session.flush()
        content = Content(subject_id=subject.id, name=f"Content {suffix}", description="d")
        session.add(content)
        await session.flush()
        return content

    async def test_create_path_raises_when_content_missing(self):
        """Creating a path requires existing content."""
        async with AsyncSessionLocal() as session:
            with self.assertRaises(LookupError):
                await self.service.create_path(
                    session=session,
                    content_id=999999,
                    name="X",
                    description=None,
                )

    async def test_add_item_raises_when_exercise_missing(self):
        """Adding an exercise item validates the target row."""
        async with AsyncSessionLocal() as session:
            content = await self._seed_content(session)
            path = Path(content_id=content.id, name="P", description=None)
            session.add(path)
            await session.flush()
            sub_path = SubPath(path_id=path.id)
            session.add(sub_path)
            await session.flush()

            with self.assertRaises(LookupError):
                await self.service.add_item(
                    session=session,
                    sub_path_id=sub_path.id,
                    type_item=TypeItemEnum.EXERCISE,
                    resource_id=None,
                    exercise_id=999999,
                    order=0,
                )

    async def test_add_transition_requires_same_path(self):
        """Transitions cannot connect sub-paths from different paths."""
        async with AsyncSessionLocal() as session:
            content = await self._seed_content(session)
            path_a = Path(content_id=content.id, name="A", description=None)
            path_b = Path(content_id=content.id, name="B", description=None)
            session.add_all([path_a, path_b])
            await session.flush()
            origin = SubPath(path_id=path_a.id)
            destination = SubPath(path_id=path_b.id)
            session.add_all([origin, destination])
            await session.flush()

            with self.assertRaises(ValueError):
                await self.service.add_transition(
                    session=session,
                    origin_id=origin.id,
                    destination_id=destination.id,
                    rule_type=RuleTypeEnum.STANDARD,
                    rule_value=None,
                )

    async def test_create_full_path_from_existing_resource_and_exercise(self):
        """The service assembles a path from existing content rows."""
        async with AsyncSessionLocal() as session:
            content = await self._seed_content(session)
            exercise = Exercise(
                content_id=content.id,
                statement="Quanto é 1+1?",
                difficulty=DifficultyEnum.EASY,
            )
            resource = Resource(
                content_id=content.id,
                type=ResourceTypeEnum.LINK,
                title="Material",
                file_url="https://example.com",
            )
            session.add_all([exercise, resource])
            await session.flush()

            path_id = await self.service.create_path(session, content.id, "Trilha", "Desc")
            sub_path_id = await self.service.add_sub_path(
                session,
                path_id=path_id,
                difficulty=DifficultyEnum.EASY,
                order=1,
            )
            resource_item_id = await self.service.add_item(
                session,
                sub_path_id=sub_path_id,
                type_item=TypeItemEnum.RESOURCE,
                resource_id=resource.id,
                exercise_id=None,
                order=1,
            )
            exercise_item_id = await self.service.add_item(
                session,
                sub_path_id=sub_path_id,
                type_item=TypeItemEnum.EXERCISE,
                resource_id=None,
                exercise_id=exercise.id,
                order=2,
            )

            self.assertGreater(path_id, 0)
            self.assertGreater(sub_path_id, 0)
            self.assertGreater(resource_item_id, 0)
            self.assertGreater(exercise_item_id, 0)
