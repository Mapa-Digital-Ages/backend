"""Store API models."""

import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from md_backend.models.db_models import (
    ClassEnum,
    DifficultyEnum,
    RuleTypeEnum,
    TaskStatusEnum,
    TypeItemEnum,
)


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
    description: str = Field(min_length=1)

    @field_validator("title", "description", mode="before")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        """Normalize required text fields before length validation."""
        return value.strip() if isinstance(value, str) else value


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

    title: str = Field(min_length=1, description="Support request title")
    description: str | None = Field(default=None, description="Support request description")
    requested_spots: int = Field(gt=0, description="Number of sponsorship spots requested")


class SponsorshipRequestResponse(BaseModel):
    """Response model for a sponsorship request."""

    id: uuid.UUID
    school_id: uuid.UUID
    title: str
    description: str | None
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


class CompanyPartnershipResponse(BaseModel):
    """A company's partnership, enriched with school name and request title."""

    id: uuid.UUID
    school_id: uuid.UUID
    school_name: str
    company_id: uuid.UUID
    request_id: uuid.UUID
    request_title: str
    granted_spots: int
    status: str
    created_at: str


class CompanyPartnershipListResponse(BaseModel):
    """List of partnerships for a single company."""

    items: list[CompanyPartnershipResponse]
    total: int


class SchoolPartnershipResponse(BaseModel):
    """A school's partnership, enriched with company name and request title."""

    id: uuid.UUID
    school_id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    request_id: uuid.UUID
    request_title: str
    granted_spots: int
    status: str
    created_at: str


class SchoolPartnershipListResponse(BaseModel):
    """List of partnerships for a single school."""

    items: list[SchoolPartnershipResponse]
    total: int


class PublicSponsorshipRequestResponse(BaseModel):
    """Response model for the public showcase listing."""

    id: uuid.UUID
    school_id: uuid.UUID
    school_name: str
    title: str
    description: str | None
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


class ValidateStepAnswerRequest(BaseModel):
    """Payload to validate one selected quiz alternative."""

    exercise_id: int
    option_id: int


class ValidateStepAnswerResponse(BaseModel):
    """Server-side validation result for one selected alternative."""

    exercise_id: int
    option_id: int
    correct: bool


class CreatePathRequest(BaseModel):
    """Request body for admin trail creation."""

    content_id: int
    name: str | None = None
    description: str | None = None


class CreateManualTrailRequest(BaseModel):
    """Request body for creating a manual quiz trail from existing content."""

    content_id: int
    name: str = Field(min_length=1)
    description: str | None = None
    eixo: list[str] = Field(min_length=1)
    question_count: int = Field(default=5, ge=1, le=20)
    difficulty: int = Field(default=1, ge=1, le=3)


class CreateManualTrailResponse(BaseModel):
    """Response for manual quiz trail creation."""

    path_id: int
    sub_path_id: int
    exercise_ids: list[int]
    item_ids: list[int]


class StructuredTrailActivityRequest(BaseModel):
    """Activity metadata for a structured trail step."""

    type: str = Field(pattern=r"^(text|video|question)$")
    question_count: int | None = Field(default=None, ge=1, le=20)
    difficulty: int | None = Field(default=None, ge=1, le=3)

    @model_validator(mode="after")
    def validate_question_settings(self):
        """Require quiz settings only for question activities."""
        if self.type == "question":
            if self.question_count is None or self.difficulty is None:
                raise ValueError("question_count and difficulty are required for question steps")
            return self
        self.question_count = None
        self.difficulty = None
        return self


class StructuredTrailSubStepRequest(BaseModel):
    """A sub-step in a structured trail step."""

    order: int = Field(ge=1)
    title: str = Field(min_length=1)
    description: str | None = None
    content_id: int
    activity: StructuredTrailActivityRequest


class StructuredTrailStepRequest(BaseModel):
    """A step in the structured trail authoring payload."""

    order: int = Field(ge=1)
    title: str = Field(min_length=1)
    description: str | None = None
    content_id: int | None = None
    activity: StructuredTrailActivityRequest | None = None
    sub_steps: list[StructuredTrailSubStepRequest] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def normalize_legacy_activity(self):
        """Accept the legacy one-activity step shape as a single sub-step."""
        if self.sub_steps:
            return self
        if self.content_id is None or self.activity is None:
            raise ValueError("sub_steps or legacy content_id/activity must be provided")
        self.sub_steps = [
            StructuredTrailSubStepRequest(
                order=1,
                title=self.title,
                description=self.description,
                content_id=self.content_id,
                activity=self.activity,
            )
        ]
        return self


class StructuredTrailRequest(BaseModel):
    """Request body for creating or replacing a full adaptive trail structure."""

    title: str = Field(min_length=1)
    description: str | None = None
    subject_id: int
    eixo: list[str] = Field(min_length=1)
    steps: list[StructuredTrailStepRequest] = Field(min_length=1)


class StructuredTrailResponse(BaseModel):
    """Response for structured trail authoring."""

    path_id: int
    sub_path_ids: list[int]
    exercise_ids: list[int]
    item_ids: list[int]


class UpdateManualTrailRequest(BaseModel):
    """Request body for editing trail metadata."""

    content_id: int | None = None
    name: str = Field(min_length=1)
    description: str | None = None


class CreateSubPathRequest(BaseModel):
    """Request body for adding a sub-path to a trail."""

    difficulty: DifficultyEnum | None = None
    order: int = 0


class AddItemRequest(BaseModel):
    """Request body for adding an existing resource or exercise to a sub-path."""

    type_item: TypeItemEnum
    resource_id: int | None = None
    exercise_id: int | None = None
    order: int = 0

    @model_validator(mode="after")
    def exactly_one_target(self):
        """Require one target and keep it aligned with type_item."""
        if (self.resource_id is None) == (self.exercise_id is None):
            raise ValueError("exactly one of resource_id/exercise_id must be set")
        if self.type_item == TypeItemEnum.RESOURCE and self.resource_id is None:
            raise ValueError("resource_id is required for resource items")
        if self.type_item == TypeItemEnum.EXERCISE and self.exercise_id is None:
            raise ValueError("exercise_id is required for exercise items")
        return self


class AddTransitionRequest(BaseModel):
    """Request body for adding an adaptive transition between sub-paths."""

    sub_path_origin_id: int
    sub_path_destination_id: int
    rule_type: RuleTypeEnum
    rule_value: int | None = None


class IdResponse(BaseModel):
    """Generic id response for trail authoring endpoints."""

    id: int


class GenerateQuestionsRequest(BaseModel):
    """Request body for offline AI question generation."""

    content_id: int | None = None
    count: int = Field(default=5, ge=1, le=20)
    difficulty: int = Field(default=1, ge=1, le=3)
    eixo: list[str] = Field(min_length=1)


class GeneratedOption(BaseModel):
    """Generated answer option for author review."""

    text: str
    correct: bool


class GeneratedQuestion(BaseModel):
    """Generated objective question persisted as an exercise."""

    statement: str
    difficulty: int = Field(ge=1, le=3)
    options: list[GeneratedOption] = Field(min_length=4, max_length=4)


class GenerateQuestionsResponse(BaseModel):
    """Response for generated content question bank."""

    content_id: int
    created_exercise_ids: list[int]
    questions: list[GeneratedQuestion]


class PartnershipStatusUpdateRequest(BaseModel):
    """Request body for PATCH /admin/partnerships/{id}/status."""

    status: str = Field(pattern=r"^(APPROVED|REJECTED|approved|rejected)$")

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        """Normalize admin status commands to the service contract."""
        return value.upper()


class PartnershipAdminResponse(BaseModel):
    """Response model for a partnership in the admin listing."""

    id: uuid.UUID
    school_id: uuid.UUID
    school_name: str
    company_id: uuid.UUID
    company_name: str
    request_id: uuid.UUID
    request_title: str
    requested_spots: int
    remaining_spots: int
    granted_spots: int
    status: str
    created_at: str


class PartnershipAdminListResponse(BaseModel):
    """Paginated list of partnerships for admin auditing."""

    items: list[PartnershipAdminResponse]
    total: int


_STUDENT_CLASS_BY_CSV_YEAR = {
    "5": ClassEnum.CLASS_5TH,
    "6": ClassEnum.CLASS_6TH,
    "7": ClassEnum.CLASS_7TH,
    "8": ClassEnum.CLASS_8TH,
    "9": ClassEnum.CLASS_9TH,
}


class StudentBatchRow(BaseModel):
    """Schema for a single row of the student batch-import CSV."""

    first_name: str = Field(min_length=1)
    last_name: str | None = Field(default=None)
    email: EmailStr
    phone_number: str | None = Field(default=None)
    birth_date: datetime.date
    student_class: ClassEnum
    school_email: str | None = Field(default=None)
    guardian_email: str | None = Field(default=None)

    @field_validator("last_name", "phone_number", "school_email", "guardian_email", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        """Convert blank strings to None before validation."""
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("birth_date", mode="before")
    @classmethod
    def parse_birth_date(cls, value):
        """Parse a birth date string in YYYY-MM-DD to a date object.

        Raises a ValueError from None when the format is invalid.
        """
        if isinstance(value, str):
            try:
                return datetime.date.fromisoformat(value.strip())
            except ValueError as err:
                raise ValueError("birth_date must be in YYYY-MM-DD format") from err
        return value

    @field_validator("student_class", mode="before")
    @classmethod
    def parse_student_class(cls, value):
        """Convert the CSV school-year number into the internal ClassEnum.

        Raises a ValueError from None when the value is invalid.
        """
        if isinstance(value, ClassEnum):
            return value

        if isinstance(value, str):
            normalized = value.strip()
            if normalized in _STUDENT_CLASS_BY_CSV_YEAR:
                return _STUDENT_CLASS_BY_CSV_YEAR[normalized]
            raise ValueError("student_class must be one of ['5', '6', '7', '8', '9']")
        return value

    def model_post_init(self, __context):
        """Post-init hook to ensure at least one contact email is provided."""
        if not self.school_email and not self.guardian_email:
            raise ValueError("At least one of school_email or guardian_email must be provided")


class StudentBatchErrorItem(BaseModel):
    """Error item resulting from validating a student batch row."""

    row: int
    email: str
    reason: str
    first_name: str | None = None
    last_name: str | None = None


class StudentBatchResponse(BaseModel):
    """Response model for student batch import results."""

    status: Literal["completed", "partial", "aborted"]
    total_processed: int
    created: int
    failed: int
    message: str
    errors: list[StudentBatchErrorItem] = []


class GuardianBatchRow(BaseModel):
    """Schema for a single row of the guardian batch-import CSV."""

    first_name: str = Field(min_length=1)
    last_name: str | None = Field(default=None)
    email: EmailStr
    phone_number: str | None = Field(default=None)

    @field_validator("last_name", "phone_number", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        """Convert blank strings to None before validation."""
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


class GuardianBatchErrorItem(BaseModel):
    """Error item resulting from validating a guardian batch row."""

    row: int
    email: str
    reason: str
    first_name: str | None = None
    last_name: str | None = None


class GuardianBatchResponse(BaseModel):
    """Response model for guardian batch import results."""

    status: Literal["completed", "partial", "aborted"]
    total_processed: int
    created: int
    failed: int
    message: str
    errors: list[GuardianBatchErrorItem] = []


class CompanyBatchRow(BaseModel):
    """Schema for a single row of the company batch-import CSV."""

    first_name: str = Field(min_length=1)
    last_name: str | None = Field(default=None)
    email: EmailStr

    @field_validator("last_name", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        """Convert blank last_name strings to None before validation."""
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


class CompanyBatchErrorItem(BaseModel):
    """Error item resulting from validating a company batch row."""

    row: int
    email: str
    reason: str
    first_name: str | None = None
    last_name: str | None = None


class CompanyBatchResponse(BaseModel):
    """Response model for company batch import results."""

    status: Literal["completed", "partial", "aborted"]
    total_processed: int
    created: int
    failed: int
    message: str
    errors: list[CompanyBatchErrorItem] = []
