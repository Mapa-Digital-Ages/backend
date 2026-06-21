"""Tests for trail authoring API schemas."""

import pytest
from pydantic import ValidationError

from md_backend.models.api_models import AddItemRequest
from md_backend.models.db_models import TypeItemEnum


def test_add_item_rejects_both_targets():
    """An authored item cannot point to resource and exercise at once."""
    with pytest.raises(ValidationError):
        AddItemRequest(
            type_item=TypeItemEnum.EXERCISE,
            resource_id=1,
            exercise_id=2,
        )


def test_add_item_rejects_no_target():
    """An authored item must point to one existing target."""
    with pytest.raises(ValidationError):
        AddItemRequest(type_item=TypeItemEnum.EXERCISE)


def test_add_item_rejects_target_that_does_not_match_type():
    """The target id must match the declared item type."""
    with pytest.raises(ValidationError):
        AddItemRequest(type_item=TypeItemEnum.EXERCISE, resource_id=1)


def test_add_item_accepts_single_matching_resource_target():
    """Resource-backed sub-steps are valid for text and video activities."""
    request = AddItemRequest(type_item=TypeItemEnum.RESOURCE, resource_id=1)

    assert request.resource_id == 1


def test_add_item_accepts_single_matching_target():
    """One matching target is valid."""
    request = AddItemRequest(type_item=TypeItemEnum.EXERCISE, exercise_id=5)

    assert request.exercise_id == 5
