"""Database models."""

import datetime
import enum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UserStatus(enum.StrEnum):
    """User approval status."""

    AGUARDANDO = "aguardando"
    NEGADO = "negado"
    APROVADO = "aprovado"


class RoleEnum(enum.StrEnum):
    """User approval status."""

    RESPONSAVEL = "responsavel"
    ADMIN = "admin"
    ALUNO = "aluno"
    ESCOLA = "escola"
    EMPRESA = "empresa"


class Base(DeclarativeBase):
    """Base class for all database models."""


class User(Base):
    """User table for authentication."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus), nullable=False, default=UserStatus.AGUARDANDO
    )
    is_superadmin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class School(Base):
    """School profile table - 1:1 with User (role=escola)."""

    __tablename__ = "schools"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    cnpj: Mapped[str] = mapped_column(String(18), unique=True, nullable=False)
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False)

class Company(Base):
    """Company table - 1:1 with User (role=empresa)."""

    __tablename__ = "companies"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    cnpj: Mapped[str] = mapped_column(String(18), unique=True, nullable=False)
