"""ORM relationships for the trail content models."""

from md_backend.models.db_models import Content, Exercise, Option, Resource


def test_exercise_has_options_and_content():
    rels = Exercise.__mapper__.relationships
    assert "options" in rels
    assert "content" in rels


def test_option_has_exercise():
    assert "exercise" in Option.__mapper__.relationships


def test_content_has_subject_exercises_resources():
    rels = Content.__mapper__.relationships
    assert {"subject", "exercises", "resources"} <= set(rels.keys())


def test_resource_has_content():
    assert "content" in Resource.__mapper__.relationships
