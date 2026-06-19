"""Store API models."""

import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from md_backend.models.db_models import ClassEnum, TaskStatusEnum


class RegisterRequest(BaseModel):
    """Register request model."""

    first_name: str = Field(min_length=1)
    last_name: str | None = Field(default=None, min_length=1)
    email: EmailStr
    password: str = Field(min_length=8)
    phone_number: str | None = None


class StudentRegisterRequest(BaseModel):
    """Register request model for student (requires school-specific fields)."""

    first_name: str = Field(min_length=1)
    last_name: str | None = Field(default=None, min_length=1)
    email: EmailStr
    password: str = Field(min_length=8)
    phone_number: str | None = None
    birth_date: datetime.date
    student_class: ClassEnum
    school_id: uuid.UUID | None = None
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
    last_name: str | None = Field(default=None, min_length=1)
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


class SubjectRequest(BaseModel):
    """Request body for creating a subject."""

    name: str = Field(min_length=1)
    color: str | None = None


class SubjectUpdateRequest(BaseModel):
    """Request body for partially updating a subject."""

    name: str | None = Field(default=None, min_length=1)
    color: str | None = None


class StudentResponse(BaseModel):
    """Response model for student creation."""

    id: uuid.UUID
    user_id: uuid.UUID
    first_name: str
    last_name: str | None
    email: str
    birth_date: str
    student_class: str
    created_at: str | None


class StudentRequest(BaseModel):
    """Request model for creating a new student."""

    first_name: str
    last_name: str | None = Field(default=None, min_length=1)
    email: EmailStr
    password: str = Field(min_length=8)
    phone_number: str | None = None
    birth_date: datetime.date
    student_class: ClassEnum
    school_id: uuid.UUID | None = None
    guardian_id: uuid.UUID | None = None


class StudentListItemResponse(BaseModel):
    """Student item returned by the paginated listing."""

    id: uuid.UUID
    user_id: uuid.UUID
    first_name: str
    last_name: str | None
    email: str
    phone_number: str
    birth_date: str
    student_class: str
    school_id: str | None
    school_name: str | None
    guardian_id: str | None
    guardian_name: str | None
    is_active: bool
    created_at: str | None


class StudentListResponse(BaseModel):
    """Paginated list of students."""

    items: list[StudentListItemResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class StudentUpdateRequest(BaseModel):
    """Request model for updating a student."""

    first_name: str | None = None
    last_name: str | None = Field(default=None, min_length=1)
    phone_number: str | None = None
    birth_date: datetime.date | None = None
    student_class: ClassEnum | None = None
    school_id: uuid.UUID | None = None
    guardian_id: uuid.UUID | None = None


class GuardianStudentResponse(BaseModel):
    """Student details returned within guardian responses."""

    user_id: uuid.UUID
    first_name: str
    last_name: str | None
    email: str
    birth_date: str
    student_class: str


class GuardianCreateRequest(BaseModel):
    """Request body for creating a guardian."""

    first_name: str
    last_name: str | None = Field(default=None, min_length=1)
    email: EmailStr
    password: str = Field(min_length=8)
    phone_number: str | None = None


class GuardianUpdateRequest(BaseModel):
    """Request body for partially updating a guardian."""

    first_name: str | None = None
    last_name: str | None = Field(default=None, min_length=1)
    email: EmailStr | None = None
    phone_number: str | None = None


class GuardianResponse(BaseModel):
    """Response model for guardian details."""

    user_id: uuid.UUID
    first_name: str
    last_name: str | None
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
    last_name: str | None = Field(default=None, min_length=1, description="Last name")
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
    last_name: str | None = Field(default=None, min_length=1)
    email: EmailStr | None = None
    is_private: bool | None = None


class SchoolResponse(BaseModel):
    """Response model for a single school."""

    user_id: uuid.UUID
    email: str
    name: str
    first_name: str
    last_name: str | None
    is_private: bool

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


class SchoolBatchRow(BaseModel):
    """Schema for a single row of the school batch-import CSV.

    Field names mirror the expected CSV headers exactly, so a dict built
    from ``csv.DictReader`` can be unpacked straight into this model.
    """

    first_name: str = Field(min_length=1)
    last_name: str | None = Field(default=None)
    email: EmailStr
    phone_number: str | None = Field(default=None)
    is_private: bool

    @field_validator("last_name", mode="before")
    @classmethod
    def blank_last_name_to_none(cls, value):
        """Treat an empty CSV cell as no last name instead of a literal ''."""
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("phone_number", mode="before")
    @classmethod
    def blank_phone_to_none(cls, value):
        """Treat an empty CSV cell as no phone number instead of a literal ''."""
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("is_private", mode="before")
    @classmethod
    def parse_is_private(cls, value):
        """Accept common CSV boolean spellings (true/false/1/0/yes/no)."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y"}:
                return True
            if normalized in {"false", "0", "no", "n"}:
                return False
            raise ValueError("is_private must be a boolean-like value (true/false)")
        return value


class SchoolBatchErrorItem(BaseModel):
    """Dados de um registro que falhou durante o batch import."""

    row: int
    email: str
    reason: str
    # Dados do elemento que deu erro
    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None
    is_private: bool | None = None


class SchoolBatchResponse(BaseModel):
    """Resposta unificada do batch import — sucesso total, parcial ou abortado."""

    status: Literal["completed", "partial", "aborted"]
    total_processed: int
    created: int
    failed: int
    message: str
    errors: list[SchoolBatchErrorItem] = []


class StudentUploadResponse(BaseModel):
    """Response model for student upload."""

    id: uuid.UUID
    student_id: uuid.UUID
    file_name: str
    download_url: str
    file_type: str
    file_size_bytes: int
    created_at: str


class ContentUpsertRequest(BaseModel):
    """Request body for creating or updating content."""

    title: str = Field(min_length=1)
    subject_id: int
    description: str | None = None


class ResourceUploadRequest(BaseModel):
    """Request body for uploading a resource file to content."""

    title: str = Field(min_length=1, description="Resource title")
    type: str = Field(
        pattern=r"^(video|pdf|presentation|link|document)$",
        description="Resource type",
    )
    url_or_contents: str | None = Field(
        default=None,
        description="URL for link type resources or additional content",
    )


class UpdateUploadRequest(BaseModel):
    """Request body for updating an upload's activity type, status, and/or subject."""

    activity_type: str | None = Field(default=None, pattern=r"^(exercise|essay|activity)$")
    status: str | None = Field(default=None, pattern=r"^(pending|in_review|corrected|rejected)$")
    subject_id: int | None = None


class WellBeingRequest(BaseModel):
    """Request body for upserting a student's well-being state."""

    humor: str | None = Field(
        default=None,
        description="Student's mood for the day.",
    )
    online_activity_minutes: int | None = Field(
        default=None,
        ge=0,
        description="Total minutes of online activity.",
    )
    sleep_hours: float | None = Field(
        default=None,
        ge=0,
        le=24,
        description="Hours of sleep last night.",
    )


class WellBeingResponse(BaseModel):
    """Response model for a student's well-being record."""

    student_id: uuid.UUID
    date: datetime.date
    humor: str | None
    online_activity_minutes: int | None
    sleep_hours: float | None


class CreateCompanyRequest(BaseModel):
    """Request body for POST /company."""

    first_name: str = Field(min_length=1, description="Primeiro nome")
    last_name: str | None = Field(default=None, min_length=1, description="Sobrenome")
    email: EmailStr = Field(description="E-mail")
    password: str = Field(min_length=8, description="Senha de acesso com mínimo de 8 caracteres")
    spots: int = Field(ge=0, description="Quantidade total de vagas")


class UpdateCompanyRequest(BaseModel):
    """Partial update body for PATCH /company/{user_id}."""

    first_name: str | None = None
    last_name: str | None = Field(default=None, min_length=1)
    email: EmailStr | None = None
    phone_number: str | None = None
    spots: int | None = None
    is_active: bool | None = None


class CompanyResponse(BaseModel):
    """Response model for a single company."""

    user_id: uuid.UUID
    email: str
    phone_number: str | None = None
    name: str
    spots: int

    status: str
    created_at: str


class CreateSponsorshipRequestRequest(BaseModel):
    """Request body for POST /school/{school_id}/requests."""

    requested_spots: int = Field(gt=0, description="Number of sponsorship spots requested")


class SponsorshipRequestResponse(BaseModel):
    """Response model for a sponsorship request."""

    id: uuid.UUID
    school_id: uuid.UUID
    requested_spots: int
    remaining_spots: int
    status: str
    created_at: str


class SponsorshipRequestListResponse(BaseModel):
    """List of sponsorship requests for a school."""

    items: list[SponsorshipRequestResponse]
    total: int


class CreatePartnershipRequest(BaseModel):
    """Request body for POST /company/{user_id}/partnerships."""

    request_id: uuid.UUID = Field(description="ID of the SponsorshipRequest to fulfill")
    granted_spots: int = Field(gt=0, description="Number of spots the company wants to donate")


class PartnershipResponse(BaseModel):
    """Response model for a donation intent (partnership)."""

    id: uuid.UUID
    school_id: uuid.UUID
    company_id: uuid.UUID
    request_id: uuid.UUID
    granted_spots: int
    status: str
    created_at: str


class PublicSponsorshipRequestResponse(BaseModel):
    """Response model for the public showcase listing."""

    id: uuid.UUID
    school_id: uuid.UUID
    school_name: str
    requested_spots: int
    remaining_spots: int
    status: str
    created_at: str


class PublicSponsorshipRequestListResponse(BaseModel):
    """Paginated public showcase of open sponsorship requests."""

    items: list[PublicSponsorshipRequestResponse]
    total: int


class CalendarTaskSubjectPayload(BaseModel):
    """Payload for the subject field in a calendar task sync request."""

    id: int


class CalendarTaskSyncItemRequest(BaseModel):
    """Request schema for a single calendar task in a sync operation."""

    id: int | str
    title: str
    task_status: TaskStatusEnum | None = None
    subject: CalendarTaskSubjectPayload
    date: datetime.datetime

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, v):
        """Coerce ISO-8601 strings (including Z suffix) to datetime."""
        if isinstance(v, str):
            return datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v

    @property
    def subject_id(self) -> int:
        """Return the nested subject id."""
        return self.subject.id

    @field_validator("task_status")
    @classmethod
    def validate_task_status(cls, value):
        """Pass through the task_status value unchanged."""
        return value


class CalendarTaskSyncResponse(BaseModel):
    """Response schema for a synced calendar task."""

    id: int
    title: str
    task_status: str | None
    subject_id: int
    date: datetime.datetime


class TaskResponse(BaseModel):
    """Response model for a single task."""

    id: int
    title: str
    task_status: str | None
    subject_id: int
    date: datetime.datetime
    deactivated_at: str | None = None


class CalendarTaskUpsertItem(BaseModel):
    """A single task item within a CalendarUpsertRequest."""

    id: int | None = None
    title: str
    task_status: TaskStatusEnum | None = None
    subject_id: int
    date: datetime.datetime | None = None


class CalendarUpsertRequest(BaseModel):
    """Request body for upserting a student's full task list for a given date."""

    tasks: list[CalendarTaskUpsertItem]


class ResourceUpdateRequest(BaseModel):
    """Request body for partially updating a resource's metadata.

    File replacement is intentionally excluded — to swap the physical file,
    delete the resource and create a new one via the upload endpoint.
    """

    title: str | None = Field(default=None, min_length=1)


class ResourceCreateRequest(BaseModel):
    """Request body for creating a metadata-only resource record.

    This is used by admin endpoints which create a Resource row pointing to an
    existing stored file or external URL.
    """

    content_id: int
    type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    file_url: str


class StepAnswer(BaseModel):
    """A single submitted answer in a sub-path quiz."""

    exercise_id: int
    option_id: int


class StepCompleteRequest(BaseModel):
    """Payload to complete a sub-path (optionally grading a quiz)."""

    answers: list[StepAnswer] = []


class PartnershipStatusUpdateRequest(BaseModel):
    """Request body for PATCH /admin/partnerships/{id}/status."""

    status: str = Field(pattern=r"^(APPROVED|REJECTED)$")


class PartnershipAdminResponse(BaseModel):
    """Response model for a partnership in the admin listing."""

    id: uuid.UUID
    school_id: uuid.UUID
    company_id: uuid.UUID
    request_id: uuid.UUID
    granted_spots: int
    status: str
    created_at: str


class PartnershipAdminListResponse(BaseModel):
    """Paginated list of partnerships for admin auditing."""

    items: list[PartnershipAdminResponse]
    total: int


class IniciarTrilhaRequest(BaseModel):
    """Request body for starting a new question trail."""

    materia: str = Field(min_length=1)
    conteudo: str = Field(min_length=1)
    eixo: list[str] = Field(min_length=1)


class PerguntaResponse(BaseModel):
    """Response model for a trail question."""

    trilha_id: str
    pergunta_id: str
    pergunta: str
    respostas: dict[str, str]
    dificuldade: int
    tentativas_restantes: int


class ResponderPerguntaRequest(BaseModel):
    """Request body for submitting an answer in a trail."""

    pergunta_id: str
    resposta: Literal["a", "b", "c", "d"]
