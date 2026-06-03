from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

import yaml
from pydantic import BaseModel, Field

from app.agents.coordinator import JobAnalysisRequest, JobAnalysisResponse, JobSearchCoordinator
from app.db.repository import JobRepository
from app.memory.profile_store import ProfileStore


class TextExpectation(BaseModel):
    field: str
    terms: list[str] = Field(default_factory=list)


class JobAnalysisExpectations(BaseModel):
    min_score: int | None = None
    max_score: int | None = None
    priority: str | None = None
    recommendation: str | None = None
    required: list[TextExpectation] = Field(default_factory=list)
    forbidden: list[TextExpectation] = Field(default_factory=list)


class JobAnalysisEvalCase(BaseModel):
    id: str
    name: str
    description: str
    job_description: str
    source_url: str | None = None
    page_title: str | None = None
    expectations: JobAnalysisExpectations


class EvalAssertionResult(BaseModel):
    name: str
    passed: bool
    expected: str
    actual: str


class JobAnalysisCaseResult(BaseModel):
    case_id: str
    name: str
    passed: bool
    score: int
    priority: str
    recommendation: str | None = None
    parser_used: str
    scorer_used: str
    guidance_used: str
    assertions: list[EvalAssertionResult] = Field(default_factory=list)


class JobAnalysisEvalReport(BaseModel):
    run_id: str
    created_at: str
    profile_path: str
    cases_path: str
    use_llm: bool
    total_cases: int
    passed_cases: int
    failed_cases: int
    results: list[JobAnalysisCaseResult] = Field(default_factory=list)


def load_eval_cases(path: Path) -> list[JobAnalysisEvalCase]:
    with path.open("r", encoding="utf-8") as cases_file:
        payload = yaml.safe_load(cases_file) or {}
    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError(f"Eval cases at {path} must be a list or a mapping with a 'cases' list.")
    return [JobAnalysisEvalCase.model_validate(raw_case) for raw_case in raw_cases]


def run_job_analysis_evals(
    cases_path: Path,
    profile_path: Path,
    use_llm: bool = False,
) -> JobAnalysisEvalReport:
    if not use_llm:
        raise ValueError("Job-analysis quality evals require --llm. Keyword-based fallback scoring has been removed.")
    cases = load_eval_cases(cases_path)
    with TemporaryDirectory(prefix="careerpilot-eval-") as temp_dir:
        coordinator = JobSearchCoordinator(
            profile_store=ProfileStore(path=profile_path),
            repository=JobRepository(Path(temp_dir) / "jobs.sqlite3"),
        )
        results = [
            evaluate_case(coordinator=coordinator, case=case, use_llm=use_llm)
            for case in cases
        ]

    passed_cases = sum(1 for result in results if result.passed)
    return JobAnalysisEvalReport(
        run_id=str(uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
        profile_path=str(profile_path),
        cases_path=str(cases_path),
        use_llm=use_llm,
        total_cases=len(results),
        passed_cases=passed_cases,
        failed_cases=len(results) - passed_cases,
        results=results,
    )


def evaluate_case(
    coordinator: JobSearchCoordinator,
    case: JobAnalysisEvalCase,
    use_llm: bool,
) -> JobAnalysisCaseResult:
    response = coordinator.analyze(
        JobAnalysisRequest(
            description=case.job_description,
            source_url=case.source_url,
            page_title=case.page_title,
            save=False,
            use_llm=use_llm,
            use_llm_guidance=use_llm,
        )
    )
    assertions = _evaluate_expectations(response, case.expectations)
    return JobAnalysisCaseResult(
        case_id=case.id,
        name=case.name,
        passed=all(assertion.passed for assertion in assertions),
        score=response.fit.score,
        priority=response.fit.priority,
        recommendation=response.fit.recommendation,
        parser_used=response.parser_used,
        scorer_used=response.scorer_used,
        guidance_used=response.guidance_used,
        assertions=assertions,
    )


def _evaluate_expectations(
    response: JobAnalysisResponse,
    expectations: JobAnalysisExpectations,
) -> list[EvalAssertionResult]:
    assertions: list[EvalAssertionResult] = []

    if expectations.min_score is not None:
        assertions.append(
            _assertion(
                name="min_score",
                passed=response.fit.score >= expectations.min_score,
                expected=f">= {expectations.min_score}",
                actual=str(response.fit.score),
            )
        )
    if expectations.max_score is not None:
        assertions.append(
            _assertion(
                name="max_score",
                passed=response.fit.score <= expectations.max_score,
                expected=f"<= {expectations.max_score}",
                actual=str(response.fit.score),
            )
        )
    if expectations.priority is not None:
        assertions.append(
            _assertion(
                name="priority",
                passed=response.fit.priority == expectations.priority,
                expected=expectations.priority,
                actual=response.fit.priority,
            )
        )
    if expectations.recommendation is not None:
        assertions.append(
            _assertion(
                name="recommendation",
                passed=response.fit.recommendation == expectations.recommendation,
                expected=expectations.recommendation,
                actual=response.fit.recommendation or "",
            )
        )

    for required in expectations.required:
        actual_text = _field_text(response, required.field)
        missing = [term for term in required.terms if term.lower() not in actual_text]
        assertions.append(
            _assertion(
                name=f"required:{required.field}",
                passed=not missing,
                expected=", ".join(required.terms),
                actual=f"missing: {', '.join(missing)}" if missing else "all present",
            )
        )

    for forbidden in expectations.forbidden:
        actual_text = _field_text(response, forbidden.field)
        present = [term for term in forbidden.terms if term.lower() in actual_text]
        assertions.append(
            _assertion(
                name=f"forbidden:{forbidden.field}",
                passed=not present,
                expected=f"absent: {', '.join(forbidden.terms)}",
                actual=f"present: {', '.join(present)}" if present else "all absent",
            )
        )

    return assertions


def _field_text(response: JobAnalysisResponse, field: str) -> str:
    field_map: dict[str, Any] = {
        "parsed.title": response.parsed_job.title,
        "parsed.company": response.parsed_job.company,
        "parsed.skills": response.parsed_job.skills,
        "fit.strong_matches": response.fit.strong_matches,
        "fit.gaps": response.fit.gaps,
        "fit.concerns": response.fit.concerns,
        "fit.summary": response.fit.summary,
        "fit.transition_notes": response.fit.transition_notes,
        "guidance.apply_reasoning": response.guidance.apply_reasoning,
        "guidance.prep_plan": response.guidance.prep_plan,
        "guidance.resume_guidance": response.guidance.resume_guidance,
        "guidance.learning_plan": response.guidance.learning_plan,
        "guidance.interview_focus": response.guidance.interview_focus,
    }
    value = field_map.get(field)
    if value is None:
        raise ValueError(f"Unsupported eval field: {field}")
    if isinstance(value, list):
        return " ".join(str(item) for item in value).lower()
    return str(value).lower()


def _assertion(name: str, passed: bool, expected: str, actual: str) -> EvalAssertionResult:
    return EvalAssertionResult(name=name, passed=passed, expected=expected, actual=actual)
