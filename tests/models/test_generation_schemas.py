"""Tests for generation API schemas."""

import pytest
from pydantic import ValidationError

from md_backend.models.api_models import GenerateQuestionsRequest


def test_request_requires_eixo():
    """Generation requires at least one eixo."""
    with pytest.raises(ValidationError):
        GenerateQuestionsRequest(content_id=1, eixo=[])


def test_request_defaults():
    """Generation defaults to five easy questions."""
    request = GenerateQuestionsRequest(content_id=1, eixo=["frações"])

    assert request.count == 5
    assert request.difficulty == 1
