"""Store API models."""

from pydantic import BaseModel


class ValidateRequest(BaseModel):
    """Validate request model."""

    num1: float
    num2: float
