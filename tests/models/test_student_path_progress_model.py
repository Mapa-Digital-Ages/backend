"""Schema invariants for StudentPathProgress."""

from md_backend.models.db_models import StudentPathProgress


def test_updated_at_is_non_null_with_onupdate():
    col = StudentPathProgress.__table__.c["updated_at"]
    assert col.nullable is False
    assert col.onupdate is not None  # onupdate must fire on UPDATE
    assert col.server_default is not None


def test_has_completed_at_nullable():
    col = StudentPathProgress.__table__.c["completed_at"]
    assert col.nullable is True


def test_has_started_at_non_null():
    col = StudentPathProgress.__table__.c["started_at"]
    assert col.nullable is False
    assert col.server_default is not None
