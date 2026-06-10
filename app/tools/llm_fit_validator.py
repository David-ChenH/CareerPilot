import json
import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config.env import load_local_env
from app.tools.job_parser import ParsedJob
from app.tools.scoring import JobFit


DEFAULT_LLM_MODEL = "gpt-4o-mini"
FIT_VALIDATION_PROMPT_VERSION = "fit-validation-prompt.v1"


ValidationStatus = Literal["pass", "repair_required", "fail"]
ValidationIssueType = Literal[
    "alternative_requirement_conflict",
    "unsupported_gap",
    "preferred_as_required",
    "unsupported_concern",
    "duplicated_semantics",
    "profile_evidence_mismatch",
    "recommendation_inconsistency",
]
ValidationSeverity = Literal["low", "medium", "high"]


class AnalysisValidationIssue(BaseModel):
    type: ValidationIssueType
    severity: ValidationSeverity
    field: str
    claim: str
    evidence: str | None = None
    repair_instruction: str


class AnalysisValidationReport(BaseModel):
    status: ValidationStatus
    issues: list[AnalysisValidationIssue] = Field(default_factory=list)
    summary: str = ""


class LLMFitValidationUnavailable(RuntimeError):
    pass


def validate_fit_with_llm(
    *,
    profile: dict[str, Any],
    job: ParsedJob,
    fit: JobFit,
) -> AnalysisValidationReport:
    client, model = _openai_client_and_model()
    try:
        response = client.responses.parse(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Validate a job-fit analysis. You are not scoring the job again. "
                        "Check whether the fit claims are supported by parsed_job and consistent with the profile. "
                        "Focus on hard gaps, growth areas, concerns, canonical labels, recommendation consistency, "
                        "and evidence grounding. Do not flag stylistic differences. "
                        "If the role lists alternative qualifications such as 'either Java, Scala or C++' and the "
                        "profile satisfies one option, any claim that the other options are hard barriers should be repaired. "
                        "Preferred, optional, useful, or ambiguous qualifications should not be hard gaps. "
                        "Return pass when issues are absent or only cosmetic. Return repair_required for fixable fit issues. "
                        "Return fail only when the fit is too unsupported to repair safely."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "profile": profile,
                            "parsed_job": job.model_dump(mode="json"),
                            "fit": fit.model_dump(mode="json"),
                        },
                        ensure_ascii=True,
                    ),
                },
            ],
            text_format=AnalysisValidationReport,
        )
    except Exception as error:
        raise LLMFitValidationUnavailable(f"LLM fit validation request failed: {error}") from error

    report = response.output_parsed
    if report is None:
        raise LLMFitValidationUnavailable("LLM fit validator returned no structured output.")
    return report


def repair_fit_with_llm(
    *,
    profile: dict[str, Any],
    job: ParsedJob,
    fit: JobFit,
    validation_report: AnalysisValidationReport,
) -> JobFit:
    client, model = _openai_client_and_model()
    try:
        response = client.responses.parse(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Repair the provided JobFit object using the validation report. "
                        "Return a complete corrected JobFit. Do not mutate parsed_job. "
                        "Remove unsupported hard gaps, downgrade preferred or alternative-satisfied items to growth areas only when useful, "
                        "deduplicate repeated ideas, and keep evidence grounded in parsed_job and profile. "
                        "Do not add new claims unless they are directly supported by parsed_job."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "profile": profile,
                            "parsed_job": job.model_dump(mode="json"),
                            "fit": fit.model_dump(mode="json"),
                            "validation_report": validation_report.model_dump(mode="json"),
                        },
                        ensure_ascii=True,
                    ),
                },
            ],
            text_format=JobFit,
        )
    except Exception as error:
        raise LLMFitValidationUnavailable(f"LLM fit repair request failed: {error}") from error

    repaired_fit = response.output_parsed
    if repaired_fit is None:
        raise LLMFitValidationUnavailable("LLM fit repair returned no structured output.")
    return repaired_fit


def _openai_client_and_model():
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMFitValidationUnavailable("OPENAI_API_KEY is not set.")

    try:
        from openai import OpenAI
    except ImportError as error:
        raise LLMFitValidationUnavailable(
            'OpenAI SDK is not installed. Install it with `pip install -e ".[dev,ai]"`.'
        ) from error

    return OpenAI(api_key=api_key), os.getenv("JOB_AGENT_LLM_MODEL", DEFAULT_LLM_MODEL)
