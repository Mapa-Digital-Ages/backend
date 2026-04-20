"""Database models."""

import datetime
import enum
import uuid
from typing import List, Optional  # noqa: UP035

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class ClassEnum(enum.StrEnum):
    """Student class enum."""

    CLASS_5TH = "5th class"
    CLASS_6TH = "6th class"
    CLASS_7TH = "7th class"
    CLASS_8TH = "8th class"
    CLASS_9TH = "9th class"


class GuardianStatusEnum(enum.StrEnum):
    """Guardian approval status."""

    WAITING = "waiting"
    APPROVED = "approved"
    REJECTED = "rejected"


class Base(DeclarativeBase):
    """Base class for all database models."""


class UserProfile(Base):
    """Main user profile, base for all others (1:1)."""

    __tablename__ = "user_profile"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password: Mapped[str] = mapped_column(String(128), nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deactivated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 1:1 Relationships
    admin_profile: Mapped[Optional["AdminProfile"]] = relationship(
        "AdminProfile", back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    student_profile: Mapped[Optional["StudentProfile"]] = relationship(
        "StudentProfile", back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    company_profile: Mapped[Optional["CompanyProfile"]] = relationship(
        "CompanyProfile", back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    school_profile: Mapped[Optional["SchoolProfile"]] = relationship(
        "SchoolProfile", back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    guardian_profile: Mapped[Optional["GuardianProfile"]] = relationship(
        "GuardianProfile", back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class AdminProfile(Base):
    """Admin specific profile."""

    __tablename__ = "admin_profile"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_profile.id"), primary_key=True
    )
    subject_area: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deactivated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["UserProfile"] = relationship("UserProfile", back_populates="admin_profile")


class StudentProfile(Base):
    """Student specific profile."""

    __tablename__ = "student_profile"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_profile.id"), primary_key=True
    )
    birth_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    student_class: Mapped[ClassEnum] = mapped_column(
        "class", Enum(ClassEnum, name="class_enum"), nullable=False
    )
    school_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("school_profile.user_id"), nullable=True
    )
    deactivated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["UserProfile"] = relationship("UserProfile", back_populates="student_profile")
    school: Mapped[Optional["SchoolProfile"]] = relationship(
        "SchoolProfile", back_populates="students"
    )
    guardians: Mapped[List["GuardianProfile"]] = relationship(
        "GuardianProfile", secondary="student_guardian", back_populates="students"
    )


class CompanyProfile(Base):
    """Company specific profile."""

    __tablename__ = "company_profile"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_profile.id"), primary_key=True
    )
    spots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_spots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deactivated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["UserProfile"] = relationship("UserProfile", back_populates="company_profile")
    schools: Mapped[List["SchoolProfile"]] = relationship(
        "SchoolProfile", secondary="school_company_partnership", back_populates="companies"
    )


class SchoolProfile(Base):
    """School specific profile."""

    __tablename__ = "school_profile"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_profile.id"), primary_key=True
    )
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requested_spots: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    deactivated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["UserProfile"] = relationship("UserProfile", back_populates="school_profile")
    students: Mapped[List["StudentProfile"]] = relationship(
        "StudentProfile", back_populates="school"
    )
    companies: Mapped[List["CompanyProfile"]] = relationship(
        "CompanyProfile", secondary="school_company_partnership", back_populates="schools"
    )


class GuardianProfile(Base):
    """Guardian specific profile."""

    __tablename__ = "guardian_profile"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_profile.id"), primary_key=True
    )
    guardian_status: Mapped[GuardianStatusEnum] = mapped_column(
        Enum(GuardianStatusEnum, name="guardian_status_enum"),
        nullable=False,
        default=GuardianStatusEnum.WAITING,
    )
    deactivated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["UserProfile"] = relationship("UserProfile", back_populates="guardian_profile")
    students: Mapped[List["StudentProfile"]] = relationship(
        "StudentProfile", secondary="student_guardian", back_populates="guardians"
    )


class SchoolCompanyPartnership(Base):
    """N:M Relationship between School and Company."""

    __tablename__ = "school_company_partnership"

    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("school_profile.user_id"), primary_key=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company_profile.user_id"), primary_key=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deactivated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StudentGuardian(Base):
    """N:M Relationship between Student and Guardian."""

    __tablename__ = "student_guardian"

    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("student_profile.user_id"), primary_key=True
    )
    guardian_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("guardian_profile.user_id"), primary_key=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deactivated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
