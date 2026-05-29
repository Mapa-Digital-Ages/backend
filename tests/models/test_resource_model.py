"""Tests for the Resource model and ResourceTypeEnum."""

import datetime
import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from md_backend.models.db_models import (
    Base,
    Content,
    Resource,
    ResourceTypeEnum,
    Subject,
    UserProfile,
)


@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def _set_fk_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s
        s.rollback()


@pytest.fixture()
def subject(session):
    subj = Subject(name=f"Math-{uuid.uuid4().hex[:6]}", slug=f"math-{uuid.uuid4().hex[:6]}")
    session.add(subj)
    session.flush()
    return subj


@pytest.fixture()
def content(session, subject):
    c = Content(subject_id=subject.id, name="Algebra Basics")
    session.add(c)
    session.flush()
    return c


class TestResourceTypeEnum:
    def test_enum_values(self):
        assert ResourceTypeEnum.VIDEO == "video"
        assert ResourceTypeEnum.PDF == "pdf"
        assert ResourceTypeEnum.PRESENTATION == "presentation"
        assert ResourceTypeEnum.LINK == "link"
        assert ResourceTypeEnum.DOCUMENT == "document"

    def test_enum_member_count(self):
        assert len(ResourceTypeEnum) == 5

    def test_enum_from_value(self):
        assert ResourceTypeEnum("video") is ResourceTypeEnum.VIDEO
        assert ResourceTypeEnum("pdf") is ResourceTypeEnum.PDF

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError, match="is not a valid"):
            ResourceTypeEnum("invalid_type")


class TestResourceModel:
    def test_create_resource_with_valid_enum(self, session, content):
        resource = Resource(
            content_id=content.id,
            type=ResourceTypeEnum.VIDEO,
            title="Intro to Algebra",
            file_name="intro.mp4",
            file_type="video/mp4",
            file_size_bytes=1024000,
            storage_key="uploads/resources/intro.mp4",
            file_url="https://storage.example.com/uploads/resources/intro.mp4",
        )
        session.add(resource)
        session.flush()

        assert resource.id is not None
        assert resource.type == ResourceTypeEnum.VIDEO
        assert resource.content_id == content.id
        assert resource.file_name == "intro.mp4"
        assert resource.file_size_bytes == 1024000

    @pytest.mark.parametrize("resource_type", list(ResourceTypeEnum))
    def test_all_enum_values_accepted(self, session, content, resource_type):
        resource = Resource(
            content_id=content.id,
            type=resource_type,
            title=f"Resource {resource_type.value}",
            file_url="https://example.com/file",
        )
        session.add(resource)
        session.flush()

        assert resource.type == resource_type

    def test_link_resource_nullable_file_fields(self, session, content):
        resource = Resource(
            content_id=content.id,
            type=ResourceTypeEnum.LINK,
            title="External Reference",
            file_url="https://docs.python.org",
        )
        session.add(resource)
        session.flush()

        assert resource.file_name is None
        assert resource.file_type is None
        assert resource.file_size_bytes is None
        assert resource.storage_key is None

    def test_invalid_enum_value_rejected(self, session, content):
        with pytest.raises(ValueError, match="is not a valid"):
            Resource(
                content_id=content.id,
                type=ResourceTypeEnum("invalid_type"),
                title="Bad Resource",
                file_url="https://example.com/file",
            )

    def test_tablename(self):
        assert Resource.__tablename__ == "resources"
