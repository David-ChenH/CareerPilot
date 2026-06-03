import json
import os
from typing import Any

from pydantic import BaseModel, Field

from app.config.env import load_local_env
from app.tools.job_parser import ParsedJob
from app.tools.scoring import JobFit


DEFAULT_LLM_MODEL = "gpt-4o-mini"


class GuidanceEvidenceItem(BaseModel):
    claim: str = Field(description="The guidance claim or action.")
    evidence_from_job: str = Field(description="Short quote or close paraphrase from the parsed job or fit evidence.")
    profile_signal: str | None = Field(default=None, description="Profile fact that supports the guidance.")
    confidence: str = Field(description="One of: high, medium, low.")


class GuidanceEvidence(BaseModel):
    apply_reasoning: list[GuidanceEvidenceItem] = Field(default_factory=list)
    prep_plan: list[GuidanceEvidenceItem] = Field(default_factory=list)
    resume_guidance: list[GuidanceEvidenceItem] = Field(default_factory=list)
    learning_plan: list[GuidanceEvidenceItem] = Field(default_factory=list)
    interview_focus: list[GuidanceEvidenceItem] = Field(default_factory=list)


class JobApplicationGuidance(BaseModel):
    apply_reasoning: list[str] = Field(
        default_factory=list,
        description="Reasons this role is or is not worth applying to.",
    )
    prep_plan: list[str] = Field(
        default_factory=list,
        description="Concrete preparation steps for this role.",
    )
    resume_guidance: list[str] = Field(
        default_factory=list,
        description="Truthful resume positioning suggestions based on supplied profile facts.",
    )
    learning_plan: list[str] = Field(
        default_factory=list,
        description="Learning priorities and small practice ideas for relevant gaps.",
    )
    interview_focus: list[str] = Field(
        default_factory=list,
        description="Topics likely to matter in interviews for this role.",
    )
    evidence: GuidanceEvidence = Field(default_factory=GuidanceEvidence)


class LLMJobGuidanceUnavailable(RuntimeError):
    pass


def generate_job_guidance_with_llm(
    profile: dict[str, Any],
    job: ParsedJob,
    fit: JobFit,
) -> JobApplicationGuidance:
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMJobGuidanceUnavailable("OPENAI_API_KEY is not set.")

    try:
        from openai import OpenAI
    except ImportError as error:
        raise LLMJobGuidanceUnavailable(
            'OpenAI SDK is not installed. Install it with `pip install -e ".[dev,ai]"`.'
        ) from error

    client = OpenAI(api_key=api_key)
    model = os.getenv("JOB_AGENT_LLM_MODEL", DEFAULT_LLM_MODEL)

    try:
        response = client.responses.parse(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Generate practical job-application guidance for a backend/AI-platform-oriented user. "
                        "Use only the supplied profile and job analysis. Do not invent experience. "
                        "Prioritize concrete preparation and resume positioning that can be acted on this week. "
                        "If the role is a career-transition bridge, explain how to position existing backend/platform experience. "
                        "Treat primary_fit.concerns as the canonical source of risks. Do not generate a separate risk list. "
                        "Ground each prep item and learning item in parsed_job or primary_fit. Do not introduce "
                        "new gaps such as Docker, Kubernetes, RAG, C++, or C# unless they appear in parsed_job or primary_fit. "
                        "If Java appears as an accepted qualification and the profile includes Java, treat it as relevant overlap. "
                        "Treat parsed_job.ambiguous_qualifications as items to validate, not as confirmed blockers. "
                        "Use primary_fit.gaps for missing required capabilities. Treat primary_fit.growth_areas as useful "
                        "preparation topics rather than blockers or required-skill gaps. "
                        "Return evidence for apply_reasoning, prep_plan, resume_guidance, learning_plan, and interview_focus."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "profile": profile,
                            "parsed_job": job.model_dump(),
                            "primary_fit": fit.model_dump(),
                        },
                        ensure_ascii=True,
                    ),
                },
            ],
            text_format=JobApplicationGuidance,
        )
    except Exception as error:
        raise LLMJobGuidanceUnavailable(f"LLM guidance request failed: {error}") from error

    guidance = response.output_parsed
    if guidance is None:
        raise LLMJobGuidanceUnavailable("LLM guidance generator returned no structured output.")
    return guidance.model_copy(
        update={
            "apply_reasoning": _dedupe_text(guidance.apply_reasoning),
            "prep_plan": _dedupe_text(guidance.prep_plan),
            "resume_guidance": _dedupe_text(guidance.resume_guidance),
            "learning_plan": _dedupe_text(guidance.learning_plan),
            "interview_focus": _dedupe_text(guidance.interview_focus),
        }
    )


def _dedupe_text(items: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for item in items:
        clean_item = " ".join(item.strip().split())
        fingerprint = clean_item.lower().rstrip(".")
        if clean_item and fingerprint not in seen:
            seen.add(fingerprint)
            deduped.append(clean_item)
    return deduped
