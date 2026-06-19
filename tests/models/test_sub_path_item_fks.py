"""SubPathItem references resources/exercises via real FKs, not a polymorphic id."""

from md_backend.models.db_models import SubPathItem


def test_has_resource_and_exercise_fks_and_no_item_id():
    cols = SubPathItem.__table__.c
    assert "resource_id" in cols
    assert "exercise_id" in cols
    assert "item_id" not in cols


def test_has_resource_and_exercise_relationships():
    rels = set(SubPathItem.__mapper__.relationships.keys())
    assert {"resource", "exercise"} <= rels
