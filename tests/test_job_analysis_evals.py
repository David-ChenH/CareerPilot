from pathlib import Path

import pytest

from app.agents.coordinator import JobAnalysisResponse
from app.evals.job_analysis import JobAnalysisExpectations, TextExpectation, _evaluate_expectations, load_eval_cases, run_job_analysis_evals
from app.tools.job_fit_taxonomy import ConcernCode, GapCode
from app.tools.job_parser import ParsedJob
from app.tools.llm_job_guidance import JobApplicationGuidance
from app.tools.scoring import EvidenceItem, JobFit


CASES_PATH = Path("evals/job_analysis/cases.yaml")
PROFILE_PATH = Path("evals/profiles/backend_ai_platform.yaml")


def test_job_analysis_eval_cases_load() -> None:
    cases = load_eval_cases(CASES_PATH)

    assert len(cases) >= 3
    assert {case.id for case in cases} >= {
        "ai-platform-backend-strong-fit",
        "research-scientist-low-fit",
        "frontend-prompt-tooling-low-fit",
        "backend-no-rag-hallucination",
        "language-alternatives-not-hard-gap",
        "preferred-ml-depth-not-blocker",
    }


def test_job_analysis_eval_runner_requires_llm() -> None:
    with pytest.raises(ValueError, match="require --llm"):
        run_job_analysis_evals(
            cases_path=CASES_PATH,
            profile_path=PROFILE_PATH,
            use_llm=False,
        )


def test_eval_expectations_detect_duplicate_items() -> None:
    response = _analysis_response(
        fit=JobFit(
            score=70,
            priority="medium",
            strong_matches=[],
            gaps=[],
            concerns=["Role may include frontend-heavy work.", "Role may include frontend-heavy work."],
            summary="Medium fit.",
        )
    )

    assertions = _evaluate_expectations(
        response,
        JobAnalysisExpectations(no_duplicates=["fit.concerns"]),
    )

    assert assertions[0].passed is False
    assert "frontend-heavy" in assertions[0].actual


def test_eval_expectations_require_evidence_for_claimed_gap() -> None:
    response = _analysis_response(
        fit=JobFit(
            score=70,
            priority="medium",
            strong_matches=[],
            gaps=["Kubernetes"],
            concerns=[],
            summary="Medium fit.",
            evidence={"gaps": []},
        )
    )

    assertions = _evaluate_expectations(
        response,
        JobAnalysisExpectations(require_evidence=[TextExpectation(field="fit.gaps", terms=["Kubernetes"])]),
    )

    assert assertions[0].passed is False
    assert assertions[0].actual == "missing evidence: Kubernetes"


def test_eval_expectations_accept_matching_evidence_for_claimed_gap() -> None:
    response = _analysis_response(
        fit=JobFit(
            score=70,
            priority="medium",
            strong_matches=[],
            gaps=["Kubernetes"],
            concerns=[],
            summary="Medium fit.",
            evidence={
                "gaps": [
                    EvidenceItem(
                        claim="Kubernetes",
                        evidence_from_job="Preferred qualifications include Kubernetes experience.",
                    )
                ]
            },
        )
    )

    assertions = _evaluate_expectations(
        response,
        JobAnalysisExpectations(require_evidence=[TextExpectation(field="fit.gaps", terms=["Kubernetes"])]),
    )

    assert assertions[0].passed is True


def test_eval_expectations_support_canonical_concern_codes() -> None:
    response = _analysis_response(
        fit=JobFit(
            score=45,
            priority="low",
            strong_matches=[],
            gaps=[],
            concerns=["Role appears frontend-heavy."],
            concern_codes=[ConcernCode.FRONTEND_HEAVY],
            summary="Low fit.",
        )
    )

    assertions = _evaluate_expectations(
        response,
        JobAnalysisExpectations(required=[TextExpectation(field="fit.concern_codes", terms=["frontend_heavy"])]),
    )

    assert assertions[0].passed is True


def test_eval_expectations_can_forbid_canonical_gap_codes() -> None:
    response = _analysis_response(
        fit=JobFit(
            score=70,
            priority="medium",
            strong_matches=[],
            gaps=["Kubernetes"],
            gap_codes=[GapCode.KUBERNETES],
            concerns=[],
            summary="Medium fit.",
        )
    )

    assertions = _evaluate_expectations(
        response,
        JobAnalysisExpectations(forbidden=[TextExpectation(field="fit.gap_codes", terms=["kubernetes"])]),
    )

    assert assertions[0].passed is False
    assert assertions[0].actual == "present: kubernetes"


def _analysis_response(fit: JobFit) -> JobAnalysisResponse:
    return JobAnalysisResponse(
        parsed_job=ParsedJob(description="Example job"),
        fit=fit,
        parser_used="test",
        scorer_used="test",
        guidance=JobApplicationGuidance(),
        guidance_used="test",
        resume_emphasis=[],
        prep_topics=[],
    )
