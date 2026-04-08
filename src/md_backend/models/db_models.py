"""Database models."""

import datetime
import enum

from sqlalchemy import Boolean, DateTime, Enum, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UserStatus(str, enum.Enum):
    """User approval status."""

    AGUARDANDO = "aguardando"
    NEGADO = "negado"
    APROVADO = "aprovado"


class Base(DeclarativeBase):
    """Base class for all database models."""


class User(Base):
    """User table for authentication."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus), nullable=False, default=UserStatus.AGUARDANDO
    )
    is_superadmin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
