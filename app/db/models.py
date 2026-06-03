from enum import StrEnum
from pydantic import BaseModel, Field

from app.artifacts import ArtifactProvenance

class ApplicationStatus(StrEnum):
    DISCOVERED = "discovered"
    INTERESTED = "interested"
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    REJECTED = "rejected"
    OFFER = "offer"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ApplicationType(StrEnum):
    INTERNAL_TRANSFER = "internal_transfer"
    EXTERNAL_APPLICATION = "external_application"
    UNKNOWN = "unknown"


class AgentTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_INPUT = "needs_input"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentTaskType(StrEnum):
    JOB_LINK_INGEST = "job_link_ingest"


class AgentTaskStep(BaseModel):
    name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    summary: str | None = None
    error: str | None = None


class AgentTask(BaseModel):
    id: str
    type: AgentTaskType
    status: AgentTaskStatus
    input: dict = Field(default_factory=dict)
    steps: list[AgentTaskStep] = Field(default_factory=list)
    artifacts: dict = Field(default_factory=dict)
    error: str | None = None
    created_at: str
    updated_at: str


class JobRecord(BaseModel):
    id: int | None = None
    source_url: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str
    skills: list[str] = Field(default_factory=list)
    fit_score: int
    priority: str
    status: ApplicationStatus = ApplicationStatus.DISCOVERED
    application_type: ApplicationType = ApplicationType.UNKNOWN
    analysis: dict | None = None
    analysis_schema_version: int | None = None
    analysis_provenance: ArtifactProvenance | None = None


class JobDetail(BaseModel):
    job: JobRecord
    analysis: dict | None = None


class JobChatMessage(BaseModel):
    id: int | None = None
    job_id: int
    role: ChatRole
    content: str
    used_web_search: bool = False
    citations: list[dict[str, str]] = Field(default_factory=list)
    created_at: str | None = None


class GlobalChatSession(BaseModel):
    id: int | None = None
    title: str = "New chat"
    created_at: str | None = None
    updated_at: str | None = None


class GlobalChatMessage(BaseModel):
    id: int | None = None
    session_id: int | None = None
    role: ChatRole
    content: str
    used_web_search: bool = False
    citations: list[dict[str, str]] = Field(default_factory=list)
    created_at: str | None = None


class PrepTask(BaseModel):
    title: str
    category: str = "learning"
    minutes: int = 30
    completed: bool = False


class PrepDay(BaseModel):
    day: int
    title: str
    tasks: list[PrepTask] = Field(default_factory=list)


class PrepPlan(BaseModel):
    id: int | None = None
    title: str
    source: str = "generated"
    timeline_days: int
    hours_per_day: float
    days: list[PrepDay] = Field(default_factory=list)
    schema_version: int = 1
    revision: int = 1
    provenance: ArtifactProvenance | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ResumeVersion(BaseModel):
    id: int | None = None
    role_title: str
    company: str | None = None
    job_id: int | None = None
    notes: str | None = None
    draft: dict
    schema_version: int = 1
    provenance: ArtifactProvenance
    created_at: str | None = None


class ProfileProposal(BaseModel):
    id: int | None = None
    filename: str | None = None
    proposed_updates: dict[str, list[str]] = Field(default_factory=dict)
    status: str = "pending"
    schema_version: int = 1
    revision: int = 1
    provenance: ArtifactProvenance
    created_at: str | None = None
    updated_at: str | None = None
