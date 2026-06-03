import os
from datetime import datetime, timezone

from pydantic import BaseModel


JOB_ANALYSIS_WORKFLOW_VERSION = "job-analysis.v5"
JOB_ANALYSIS_PROMPT_VERSION = "job-analysis-prompts.v5"
PREP_PLAN_WORKFLOW_VERSION = "prep-plan.v1"
PREP_PLAN_PROMPT_VERSION = "prep-plan-prompt.v1"
RESUME_WORKFLOW_VERSION = "resume-draft.v1"
RESUME_PROMPT_VERSION = "resume-draft-prompt.v1"
PROFILE_PROPOSAL_WORKFLOW_VERSION = "profile-proposal.v1"
PROFILE_PROPOSAL_PROMPT_VERSION = "profile-proposal-prompt.v1"


class ArtifactProvenance(BaseModel):
    generator: str
    workflow_version: str
    schema_version: int
    prompt_version: str | None = None
    model: str | None = None
    created_at: str


def artifact_provenance(
    *,
    generator: str,
    workflow_version: str,
    schema_version: int,
    prompt_version: str | None = None,
    model: str | None = None,
) -> ArtifactProvenance:
    return ArtifactProvenance(
        generator=generator,
        workflow_version=workflow_version,
        schema_version=schema_version,
        prompt_version=prompt_version,
        model=model,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def configured_llm_model(default: str) -> str:
    return os.getenv("JOB_AGENT_LLM_MODEL", default)
