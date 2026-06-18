import json
import os
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.config.env import load_local_env
from app.db.models import GlobalChatMessage, JobRecord
from app.tools.llm_job_chat import DEFAULT_LLM_MODEL


class AssistantPlannerUnavailable(RuntimeError):
    pass


class AssistantPlanStatus(StrEnum):
    ANSWER_ONLY = "answer_only"
    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECTED = "rejected"


class ActionExecutionStatus(StrEnum):
    EXECUTED = "executed"
    REJECTED = "rejected"
    FAILED = "failed"
    NEEDS_CONFIRMATION = "needs_confirmation"


class ProfileUpdateArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    background: list[str] = Field(default_factory=list)
    technical_strengths: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    experience_highlights: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    career_goals: list[str] = Field(default_factory=list)
    learning_goals: list[str] = Field(default_factory=list)
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    unknown_or_to_confirm: list[str] = Field(default_factory=list)

    def to_updates(self) -> dict[str, list[str]]:
        return {
            key: values
            for key, values in self.model_dump(mode="json").items()
            if values
        }


class AssistantActionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = None
    save: bool = False
    proposed_updates: ProfileUpdateArguments = Field(default_factory=ProfileUpdateArguments)
    timeline_days: int | None = Field(default=None, ge=1, le=365)
    hours_per_day: float | None = Field(default=None, ge=0.25, le=24)
    focus: str | None = None
    job_id: int | None = None
    role_title: str | None = None
    company: str | None = None
    notes: str | None = None
    job_ids: list[int] = Field(default_factory=list)


class AssistantPlannedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Allow-listed application action name.")
    arguments: AssistantActionArguments = Field(default_factory=AssistantActionArguments)
    target_context: str | None = Field(default=None, description="Short description of the page, job, profile, or object this action targets.")
    confidence: float = Field(default=0, ge=0, le=1)
    approval_required: bool = True
    approval_confirmed: bool = False
    reason: str | None = None


class AssistantPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_summary: str
    status: AssistantPlanStatus = AssistantPlanStatus.ANSWER_ONLY
    actions: list[AssistantPlannedAction] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
    clarification_question: str | None = None


class ActionExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_name: str
    status: ActionExecutionStatus
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


def plan_assistant_actions_with_llm(
    *,
    profile: dict[str, Any],
    jobs: list[JobRecord],
    messages: list[GlobalChatMessage],
    active_context: dict[str, Any] | None = None,
) -> AssistantPlan:
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise AssistantPlannerUnavailable("OPENAI_API_KEY is not set.")

    try:
        from openai import OpenAI
    except ImportError as error:
        raise AssistantPlannerUnavailable(
            'OpenAI SDK is not installed. Install it with `pip install -e ".[dev,ai]"`.'
        ) from error

    client = OpenAI(api_key=api_key)
    model = os.getenv("JOB_AGENT_PLANNER_MODEL", os.getenv("JOB_AGENT_LLM_MODEL", DEFAULT_LLM_MODEL))

    try:
        response = client.responses.parse(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are the assistant planner for CareerPilot. Your job is to decide whether the latest "
                        "user message should invoke approved application actions or should be answered by the normal "
                        "chat assistant. You do not produce the final conversational answer unless you need a "
                        "clarification or confirmation prompt. Interpret user intent semantically, including typos, "
                        "multi-intent messages, and follow-up confirmations. Return multiple actions when the user "
                        "asks for multiple distinct tasks. Use only these action names: ingest_job_from_url, "
                        "update_profile_memory, generate_prep_plan, generate_resume, compare_saved_jobs. "
                        "Every action must include an arguments object with all schema fields; use null, false, "
                        "or empty lists for fields that do not apply. "
                        "Return answer_only with no actions for ordinary questions, strategy "
                        "discussion, or requests that require a conversational answer. Return needs_clarification "
                        "when the target object or requested action is ambiguous. Return rejected only for unsafe or "
                        "unsupported external actions. For ingest_job_from_url, arguments must include url and save. "
                        "Set save=true only when the user asks to save, track, apply, add to tracker, or persist the "
                        "job; set save=false for analyze/fetch/preview only. Saving a job mutates the application "
                        "tracker, so approval_required must be true and approval_confirmed must be false unless the "
                        "latest user message is clearly confirming a previously proposed save action. For "
                        "update_profile_memory, put facts into proposed_updates using only these fields: background, "
                        "technical_strengths, education, experience_highlights, target_roles, career_goals, "
                        "learning_goals, must_have, nice_to_have, avoid, unknown_or_to_confirm. Profile memory "
                        "updates always require approval. Set "
                        "approval_confirmed=true only when the latest user message clearly confirms a previously "
                        "proposed profile update. For generate_prep_plan, use timeline_days, hours_per_day, "
                        "focus, and optional job_id. It saves a prep plan, so approval is required. For "
                        "generate_resume, use role_title, company, optional job_id, and notes. It saves a resume "
                        "version, so approval is required. For compare_saved_jobs, use job_ids when the user "
                        "mentions specific saved jobs; otherwise leave job_ids empty to compare active saved jobs. "
                        "Comparing jobs is read-only and does not require approval. Never invent unsupported "
                        "action names or generated code."
                    ),
                },
                {
                    "role": "system",
                    "content": "Local planning context JSON: "
                    + json.dumps(
                        {
                            "active_context": active_context or {"type": "global"},
                            "profile": profile,
                            "saved_jobs": [_summarize_job(job) for job in jobs[:20]],
                        },
                        ensure_ascii=True,
                    ),
                },
                *[
                    {
                        "role": message.role.value,
                        "content": message.content,
                    }
                    for message in messages[-12:]
                ],
            ],
            text_format=AssistantPlan,
        )
    except Exception as error:
        raise AssistantPlannerUnavailable(f"Assistant planner request failed: {error}") from error

    plan = response.output_parsed
    if plan is None:
        raise AssistantPlannerUnavailable("Assistant planner returned no structured plan.")
    return plan


def _summarize_job(job: JobRecord) -> dict[str, Any]:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "source_url": job.source_url,
        "status": job.status.value,
        "priority": job.priority,
        "fit_score": job.fit_score,
    }
