"""Unit tests for ResourceService orchestration and persistence."""

import asyncio
import unittest
import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from md_backend.models.db_models import Base, Content, Resource, Subject
from md_backend.services.resource_service import ResourceService
from md_backend.services.storage_service import StorageService


class MockStorage(StorageService):
    """In-memory storage fake for normal upload and delete flows."""

    def __init__(self):
        """Create an empty in-memory store used by the mock methods."""
        self.store: dict[uuid.UUID, bytes] = {}

    async def upload_file(self, upload_id, storage_key, file_bytes, content_type):
        self.store[upload_id] = file_bytes

    async def read_file(self, upload_id, storage_key):
        return self.store.get(upload_id)

    async def delete_file(self, upload_id, storage_key):
        self.store.pop(upload_id, None)


class FailingDeleteStorage(StorageService):
    """Storage fake that fails on delete to verify DB consistency."""

    def __init__(self):
        """Create an empty in-memory store used by the mock methods."""
        self.store: dict[uuid.UUID, bytes] = {}

    async def upload_file(self, upload_id, storage_key, file_bytes, content_type):
        self.store[upload_id] = file_bytes

    async def read_file(self, upload_id, storage_key):
        return self.store.get(upload_id)

    async def delete_file(self, upload_id, storage_key):
        raise RuntimeError("storage delete failure")


async def _create_session() -> tuple[AsyncSession, AsyncEngine]:
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine, expire_on_commit=False
    )
    session: AsyncSession = async_session()
    return session, engine


class TestResourceService(unittest.TestCase):
    def test_upload_resource_persists_metadata_and_calls_storage(self):
        async def run_test():
            session, engine = await _create_session()
            async with session as db_session:
                subject = Subject(name="Math Test", slug="math-test")
                db_session.add(subject)
                await db_session.commit()
                content = Content(subject_id=subject.id, name="Algebra")
                db_session.add(content)
                await db_session.commit()

                storage = MockStorage()
                service = ResourceService(storage=storage)
                result = await service.upload_resource(
                    session=db_session,
                    file_bytes=b"%PDF-1.4 fake content",
                    title="Lesson Plan",
                    resource_type="pdf",
                    content_id=content.id,
                    file_name="lesson.pdf",
                    file_type="application/pdf",
                )

                self.assertIsInstance(result, dict)
                result = cast(dict, result)
                self.assertIn("id", result)
                self.assertEqual(result["file_name"], "lesson.pdf")
                self.assertEqual(result["type"], "pdf")
                self.assertIsInstance(result["created_at"], str)
                self.assertEqual(len(storage.store), 1)
                upper_case_result = await service.upload_resource(
                    session=db_session,
                    file_bytes=b"%PDF-1.4 fake content",
                    title="Lesson Plan Upper",
                    resource_type="PDF",
                    content_id=content.id,
                    file_name="lesson_upper.pdf",
                    file_type="application/pdf",
                )
                self.assertIsInstance(upper_case_result, dict)
                upper_case_result = cast(dict, upper_case_result)
                self.assertEqual(upper_case_result["type"], "pdf")

                row = await db_session.execute(select(Resource).where(Resource.id == result["id"]))
                persisted = row.scalar_one_or_none()
                self.assertIsNotNone(persisted)
                persisted = cast(Resource, persisted)
                self.assertEqual(persisted.title, "Lesson Plan")
                self.assertEqual(persisted.file_url, result["file_url"])

            await engine.dispose()

        asyncio.run(run_test())

    def test_upload_resource_rejects_invalid_type_and_too_large_files(self):
        async def run_test():
            session, engine = await _create_session()
            async with session as db_session:
                subject = Subject(name="Science Test", slug="science-test")
                db_session.add(subject)
                await db_session.commit()
                content = Content(subject_id=subject.id, name="Biology")
                db_session.add(content)
                await db_session.commit()

                storage = MockStorage()
                service = ResourceService(storage=storage)

                invalid_type = await service.upload_resource(
                    session=db_session,
                    file_bytes=b"hello",
                    title="Bad Resource",
                    resource_type="link",
                    content_id=content.id,
                    file_name="link.txt",
                    file_type="text/plain",
                )
                self.assertEqual(invalid_type, "invalid_resource_type")

                too_large = await service.upload_resource(
                    session=db_session,
                    file_bytes=b"x" * (50 * 1024 * 1024 + 1),
                    title="Huge PDF",
                    resource_type="pdf",
                    content_id=content.id,
                    file_name="huge.pdf",
                    file_type="application/pdf",
                )
                self.assertEqual(too_large, "file_too_large")

            await engine.dispose()

        asyncio.run(run_test())

    def test_get_resource_returns_metadata(self):
        async def run_test():
            session, engine = await _create_session()
            async with session as db_session:
                subject = Subject(name="History Test", slug="history-test")
                db_session.add(subject)
                await db_session.commit()
                content = Content(subject_id=subject.id, name="History")
                db_session.add(content)
                await db_session.commit()

                resource = Resource(
                    content_id=content.id,
                    type="pdf",
                    title="Chapter 1",
                    file_url="/api/resources/test.pdf",
                )
                db_session.add(resource)
                await db_session.commit()
                await db_session.refresh(resource)

                service = ResourceService(storage=MockStorage())
                result = await service.get_resource(session=db_session, resource_id=resource.id)
                self.assertIsInstance(result, dict)
                result = cast(dict, result)
                self.assertEqual(result["id"], resource.id)
                self.assertEqual(result["title"], "Chapter 1")

            await engine.dispose()

        asyncio.run(run_test())

    def test_list_resources_supports_pagination(self):
        async def run_test():
            session, engine = await _create_session()
            async with session as db_session:
                subject = Subject(name="Arts Test", slug="arts-test")
                db_session.add(subject)
                await db_session.commit()
                content = Content(subject_id=subject.id, name="Arts")
                db_session.add(content)
                await db_session.commit()

                for index in range(3):
                    db_session.add(
                        Resource(
                            content_id=content.id,
                            type="pdf",
                            title=f"Document {index}",
                            file_url=f"/api/resources/doc-{index}.pdf",
                        )
                    )
                await db_session.commit()

                service = ResourceService(storage=MockStorage())
                page = await service.list_resources(
                    session=db_session, content_id=content.id, page=1, page_size=2
                )
                self.assertIsInstance(page, dict)
                page = cast(dict, page)

                self.assertEqual(page["page"], 1)
                self.assertEqual(page["page_size"], 2)
                self.assertEqual(page["total"], 3)
                self.assertEqual(len(page["items"]), 2)

            await engine.dispose()

        asyncio.run(run_test())

    def test_delete_resource_removes_storage_and_db_row(self):
        async def run_test():
            session, engine = await _create_session()
            async with session as db_session:
                subject = Subject(name="Physics Test", slug="physics-test")
                db_session.add(subject)
                await db_session.commit()
                content = Content(subject_id=subject.id, name="Physics")
                db_session.add(content)
                await db_session.commit()

                storage = MockStorage()
                service = ResourceService(storage=storage)
                created = await service.upload_resource(
                    session=db_session,
                    file_bytes=b"%PDF-1.4 content",
                    title="Syllabus",
                    resource_type="pdf",
                    content_id=content.id,
                    file_name="syllabus.pdf",
                    file_type="application/pdf",
                )
                self.assertIsInstance(created, dict)
                created = cast(dict, created)

                resource_id: int = int(created["id"])
                deleted = await service.delete_resource(session=db_session, resource_id=resource_id)
                self.assertTrue(deleted)

                row = await db_session.execute(select(Resource).where(Resource.id == created["id"]))
                self.assertIsNone(row.scalar_one_or_none())
                self.assertEqual(len(storage.store), 0)

            await engine.dispose()

        asyncio.run(run_test())

    def test_delete_resource_does_not_remove_db_when_storage_fails(self):
        async def run_test():
            session, engine = await _create_session()
            async with session as db_session:
                subject = Subject(name="Geography Test", slug="geography-test")
                db_session.add(subject)
                await db_session.commit()
                content = Content(subject_id=subject.id, name="Geography")
                db_session.add(content)
                await db_session.commit()

                resource = Resource(
                    content_id=content.id,
                    type="pdf",
                    title="Map",
                    file_url="/api/resources/map.pdf",
                    storage_key="resources/1/failing/map.pdf",
                )
                db_session.add(resource)
                await db_session.commit()
                await db_session.refresh(resource)
                resource_id = resource.id

                storage = FailingDeleteStorage()
                service = ResourceService(storage=storage)
                result = await service.delete_resource(session=db_session, resource_id=resource_id)
                self.assertFalse(result)

                row = await db_session.execute(select(Resource).where(Resource.id == resource_id))
                self.assertIsNotNone(row.scalar_one_or_none())

            await engine.dispose()

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
