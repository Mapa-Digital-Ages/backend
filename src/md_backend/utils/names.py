"""Helpers for user-facing names."""


def build_full_name(first_name: str, last_name: str | None) -> str:
    """Build a display name without rendering null surname values."""
    return " ".join(part for part in (first_name, last_name) if part).strip()
