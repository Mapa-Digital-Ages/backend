"""Store API models."""

from pydantic import BaseModel


class ValidateRequest(BaseModel):
    """Validate request model."""

    num1: int
    num2: int
