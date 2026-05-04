"""Store API models."""

import datetime
import uuid

from pydantic import BaseModel, EmailStr, Field

from md_backend.models.db_models import ClassEnum


class RegisterRequest(BaseModel):
    """Register request model."""

    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=8)
    phone_number: str | None = None


class StudentRegisterRequest(BaseModel):
    """Register request model for student (requires school-specific fields)."""

    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=8)
    phone_number: str | None = None
    birth_date: datetime.date
    student_class: ClassEnum
    school_id: uuid.UUID | None = None


class LoginRequest(BaseModel):
    """Login request model."""

    email: EmailStr
    password: str


class PasswordResetRequest(BaseModel):
    """Request body for generating a password reset code."""

    email: EmailStr


class PasswordResetRequestResponse(BaseModel):
    """Response body for password reset requests."""

    detail: str


class PasswordResetConfirmRequest(BaseModel):
    """Request body for confirming a password reset."""

    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8)


class SetupRequest(BaseModel):
    """Setup request model for creating the first superadmin."""

    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=8)
    phone_number: str | None = None


class UserResponse(BaseModel):
    """User data for admin listing."""

    id: str
    email: str
    name: str
    status: str
    is_superadmin: bool
    created_at: str


class UpdateStatusRequest(BaseModel):
    """Request to update user approval status."""

    status: str = Field(pattern=r"^(approved|rejected|waiting)$")


class StudentResponse(BaseModel):
    """Response model for student creation."""

    id: uuid.UUID
    user_id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    birth_date: str
    student_class: str
    created_at: str | None


class StudentRequest(BaseModel):
    """Request model for creating a new student."""

    first_name: str
    last_name: str
    email: EmailStr
    password: str = Field(min_length=8)
    phone_number: str | None = None
    birth_date: datetime.date
    student_class: ClassEnum
    school_id: uuid.UUID | None = None


class StudentListResponse(BaseModel):
    """Response model for student listing."""

    id: uuid.UUID
    user_id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    phone_number: str
    birth_date: str
    student_class: str
    school_id: str
    is_active: bool
    created_at: str | None


class StudentUpdateRequest(BaseModel):
    """Request model for updating a student."""

    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None
    birth_date: datetime.date | None = None
    student_class: ClassEnum | None = None
    school_id: uuid.UUID | None = None


class GuardianStudentResponse(BaseModel):
    """Student details returned within guardian responses."""

    user_id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    birth_date: str
    student_class: str


class GuardianCreateRequest(BaseModel):
    """Request body for creating a guardian."""

    first_name: str
    last_name: str
    email: EmailStr
    password: str = Field(min_length=8)
    phone_number: str | None = None


class GuardianUpdateRequest(BaseModel):
    """Request body for partially updating a guardian."""

    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    phone_number: str | None = None


class GuardianResponse(BaseModel):
    """Response model for guardian details."""

    user_id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    phone_number: str | None = None
    guardian_status: str
    is_active: bool
    created_at: str | None
    deactivated_at: str | None
    students: list[GuardianStudentResponse]


class GuardianListPaginatedResponse(BaseModel):
    """Paginated list of guardians."""

    items: list[GuardianResponse]
    total: int
    page: int
    size: int


class CreateSchoolRequest(BaseModel):
    """Request body for POST /school."""

    first_name: str = Field(min_length=1, description="First name")
    last_name: str = Field(min_length=1, description="Last name")
    email: EmailStr = Field(description="Email")
    password: str = Field(min_length=8, description="Access password with at least 8 characters")
    phone_number: str | None = Field(default=None, description="Optional phone number")
    is_private: bool = Field(description="Whether the school is public or private")
    requested_spots: int | None = Field(
        default=None, description="Requested spots (public schools only)"
    )


class UpdateSchoolRequest(BaseModel):
    """Partial update body for PATCH /school/{id}."""

    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    is_private: bool | None = None
    requested_spots: int | None = None


class SchoolResponse(BaseModel):
    """Response model for a single school."""

    user_id: uuid.UUID
    email: str
    name: str
    is_private: bool
    requested_spots: int | None
    is_active: bool
    deactivated_at: str | None
    created_at: str
    student_count: int


class SchoolListResponse(BaseModel):
    """Paginated list of schools."""

    items: list[SchoolResponse]
    total: int
    page: int
    size: int


class StudentUploadResponse(BaseModel):
    """Response model for student upload."""

    id: uuid.UUID
    student_id: uuid.UUID
    file_name: str
    download_url: str
    file_type: str
    file_size_bytes: int
    created_at: str
