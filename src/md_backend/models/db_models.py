"""Database models."""

import datetime
import enum
import uuid
from typing import Optional  # noqa: UP035

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
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
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deactivated_at: Mapped[datetime.datetime | None] = mapped_column(
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
    subject_area: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deactivated_at: Mapped[datetime.datetime | None] = mapped_column(
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
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("school_profile.user_id"), nullable=True
    )
    deactivated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["UserProfile"] = relationship("UserProfile", back_populates="student_profile")
    school: Mapped[Optional["SchoolProfile"]] = relationship(
        "SchoolProfile", back_populates="students"
    )
    guardians: Mapped[list["GuardianProfile"]] = relationship(
        "GuardianProfile", secondary="student_guardian", back_populates="students"
    )
    uploads: Mapped[list["StudentUpload"]] = relationship(
        "StudentUpload", back_populates="student", cascade="all, delete-orphan"
    )


class CompanyProfile(Base):
    """Company specific profile."""

    __tablename__ = "company_profile"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_profile.id"), primary_key=True
    )
    spots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_spots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deactivated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["UserProfile"] = relationship("UserProfile", back_populates="company_profile")
    schools: Mapped[list["SchoolProfile"]] = relationship(
        "SchoolProfile", secondary="school_company_partnership", back_populates="companies"
    )


class SchoolProfile(Base):
    """School specific profile."""

    __tablename__ = "school_profile"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_profile.id"), primary_key=True
    )
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requested_spots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deactivated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["UserProfile"] = relationship("UserProfile", back_populates="school_profile")
    students: Mapped[list["StudentProfile"]] = relationship(
        "StudentProfile", back_populates="school"
    )
    companies: Mapped[list["CompanyProfile"]] = relationship(
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
    deactivated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["UserProfile"] = relationship("UserProfile", back_populates="guardian_profile")
    students: Mapped[list["StudentProfile"]] = relationship(
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
    deactivated_at: Mapped[datetime.datetime | None] = mapped_column(
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
    deactivated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DifficultyEnum(enum.StrEnum):
    """Difficulty levels for exercises and paths."""

    VERY_EASY = "very_easy"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    VERY_HARD = "very_hard"


class PathStatusEnum(enum.StrEnum):
    """Path progress status."""

    ON_GOING = "on_going"
    COMPLETED = "completed"
    PAUSED = "paused"


class TypeItemEnum(enum.StrEnum):
    """Sub-path item type."""

    RESOURCE = "resource"
    EXERCISE = "exercise"


class RuleTypeEnum(enum.StrEnum):
    """Path transition rule type."""

    BIGGER_THAN = "bigger_than"
    SMALLER_THAN = "smaller_than"
    STANDARD = "standard"


class TaskStatusEnum(enum.StrEnum):
    """Task progress status."""

    PENDING = "pending"
    COMPLETED = "completed"


class HumorEnum(enum.StrEnum):
    """Well being humor."""

    BAD = "bad"
    REGULAR = "regular"
    GOOD = "good"


class Subject(Base):
    """Subject table."""

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)


class Content(Base):
    """Content table."""

    __tablename__ = "contents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(Integer, ForeignKey("subjects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Resource(Base):
    """Resource table."""

    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contents_id: Mapped[int] = mapped_column(Integer, ForeignKey("contents.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    url_or_contents: Mapped[str | None] = mapped_column(Text, nullable=True)


class Exercise(Base):
    """Exercise table."""

    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contents_id: Mapped[int] = mapped_column(Integer, ForeignKey("contents.id"), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[DifficultyEnum] = mapped_column(
        Enum(DifficultyEnum, name="difficulty_enum"), nullable=False
    )


class Option(Base):
    """Options for exercises."""

    __tablename__ = "options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(Integer, ForeignKey("exercises.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)


class Attempt(Base):
    """Student exercise attempt record."""

    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("student_profile.user_id"), nullable=False
    )
    exercise_id: Mapped[int] = mapped_column(Integer, ForeignKey("exercises.id"), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Path(Base):
    """Adaptive learning paths."""

    __tablename__ = "paths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contents_id: Mapped[int] = mapped_column(Integer, ForeignKey("contents.id"), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class SubPath(Base):
    """Sub-paths for adaptive learning."""

    __tablename__ = "sub_paths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path_id: Mapped[int] = mapped_column(Integer, ForeignKey("paths.id"), nullable=False)
    difficulty: Mapped[DifficultyEnum | None] = mapped_column(
        Enum(DifficultyEnum, name="difficulty_enum"), nullable=True
    )


class SubPathItem(Base):
    """Items inside a sub-path."""

    __tablename__ = "sub_paths_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sub_path_id: Mapped[int] = mapped_column(Integer, ForeignKey("sub_paths.id"), nullable=False)
    type_item: Mapped[TypeItemEnum] = mapped_column(
        Enum(TypeItemEnum, name="type_item_enum"), nullable=False
    )
    item_id: Mapped[int] = mapped_column(Integer, nullable=False)


class PathTransition(Base):
    """Transition rules between sub-paths."""

    __tablename__ = "path_transition"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sub_path_origem_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sub_paths.id"), nullable=True
    )
    sub_path_destino_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sub_paths.id"), nullable=True
    )
    rule_type: Mapped[RuleTypeEnum | None] = mapped_column(
        Enum(RuleTypeEnum, name="rule_type_enum"), nullable=True
    )
    rule_value: Mapped[int | None] = mapped_column(Integer, nullable=True)


class StudentPathProgress(Base):
    """Student progress tracking for a path."""

    __tablename__ = "student_path_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("student_profile.user_id"), nullable=False
    )
    path_id: Mapped[int] = mapped_column(Integer, ForeignKey("paths.id"), nullable=False)
    current_sub_path: Mapped[int] = mapped_column(
        Integer, ForeignKey("sub_paths.id"), nullable=False
    )
    path_status: Mapped[PathStatusEnum | None] = mapped_column(
        Enum(PathStatusEnum, name="path_status_enum"), nullable=True
    )
    updated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WellBeing(Base):
    """Student well-being tracking."""

    __tablename__ = "well_being"

    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("student_profile.user_id"), primary_key=True, nullable=False
    )
    date: Mapped[datetime.date] = mapped_column(
        Date, primary_key=True, server_default=func.current_date()
    )
    humor: Mapped[HumorEnum | None] = mapped_column(
        Enum(HumorEnum, name="humor_enum"), nullable=True
    )
    online_activity_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_hours: Mapped[float | None] = mapped_column(Numeric, nullable=True)


class Task(Base):
    """Tasks for students."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("student_profile.user_id"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    task_status: Mapped[TaskStatusEnum | None] = mapped_column(
        Enum(TaskStatusEnum, name="task_status_enum"), nullable=True
    )
    date: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deactivated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StudentContentProgress(Base):
    """Content mastery tracking per student."""

    __tablename__ = "student_content_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("student_profile.user_id"), nullable=False
    )
    content_id: Mapped[int] = mapped_column(Integer, ForeignKey("contents.id"), nullable=False)
    mastery_level: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    created_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    deactivated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class LoginHistory(Base):
    """Login history across all users."""

    __tablename__ = "login_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_profile.id"), nullable=False
    )
    created_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    deactivated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StudentUpload(Base):
    """File uploads by students."""

    __tablename__ = "student_uploads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("student_profile.user_id"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    student: Mapped["StudentProfile"] = relationship("StudentProfile", back_populates="uploads")
