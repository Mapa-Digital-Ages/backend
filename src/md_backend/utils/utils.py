"""Helpers for user-facing names."""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

_enabled = os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false"
limiter = Limiter(key_func=get_remote_address, enabled=_enabled)


def build_full_name(first_name: str, last_name: str | None) -> str:
    """Build a display name without rendering null surname values."""
    return " ".join(part for part in (first_name, last_name) if part).strip()
