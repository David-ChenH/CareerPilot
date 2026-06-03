from enum import StrEnum

from pydantic import BaseModel, Field

from app.workflows.trace import WorkflowTraceEvent

class ModelTier(StrEnum):
    NONE = "none"
    CHEAP = "cheap"
    STANDARD = "standard"
    STRONG = "strong"


class WorkflowTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    WAITING_FOR_APPROVAL = "waiting_for_approval"


class WorkflowRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_FOR_APPROVAL = "waiting_for_approval"


class WorkflowTask(BaseModel):
    id: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    description: str = ""
    dependencies: list[str] = Field(default_factory=list)
    input: dict = Field(default_factory=dict)
    status: WorkflowTaskStatus = WorkflowTaskStatus.PENDING
    model_tier: ModelTier = ModelTier.NONE
    retry_count: int = Field(default=0, ge=0)
    cache_key: str | None = None
    estimated_cost_usd: float = Field(default=0, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    error_type: str | None = None
    requires_approval: bool = False


class WorkflowDefinition(BaseModel):
    id: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    description: str = ""
    tasks: list[WorkflowTask] = Field(min_length=1)
    budget_usd: float | None = Field(default=None, ge=0)


class WorkflowRun(BaseModel):
    id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    workflow_version: int = Field(ge=1)
    status: WorkflowRunStatus = WorkflowRunStatus.PENDING
    tasks: list[WorkflowTask]
    outputs: dict = Field(default_factory=dict)
    total_estimated_cost_usd: float = Field(default=0, ge=0)
    total_latency_ms: int = Field(default=0, ge=0)
    cache_hits: int = Field(default=0, ge=0)
    cache_misses: int = Field(default=0, ge=0)
    trace_events: list[WorkflowTraceEvent] = Field(default_factory=list)


class WorkflowGraphNode(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    description: str = ""
    status: WorkflowTaskStatus = WorkflowTaskStatus.PENDING


class WorkflowGraphEdge(BaseModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)


class WorkflowGraph(BaseModel):
    workflow_id: str = Field(min_length=1)
    workflow_version: int = Field(ge=1)
    nodes: list[WorkflowGraphNode]
    edges: list[WorkflowGraphEdge]
