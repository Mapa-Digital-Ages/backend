"""FK columns to contents use the singular content_id naming."""

from md_backend.models.db_models import Exercise, Path


def test_path_uses_content_id():
    cols = Path.__table__.c
    assert "content_id" in cols
    assert "contents_id" not in cols


def test_exercise_uses_content_id():
    cols = Exercise.__table__.c
    assert "content_id" in cols
    assert "contents_id" not in cols
