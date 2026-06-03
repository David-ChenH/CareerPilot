from pathlib import Path

import pytest

from app.evals.job_analysis import load_eval_cases, run_job_analysis_evals


CASES_PATH = Path("evals/job_analysis/cases.yaml")
PROFILE_PATH = Path("evals/profiles/backend_ai_platform.yaml")


def test_job_analysis_eval_cases_load() -> None:
    cases = load_eval_cases(CASES_PATH)

    assert len(cases) >= 3
    assert {case.id for case in cases} >= {
        "ai-platform-backend-strong-fit",
        "research-scientist-low-fit",
        "frontend-prompt-tooling-low-fit",
    }


def test_job_analysis_eval_runner_requires_llm() -> None:
    with pytest.raises(ValueError, match="require --llm"):
        run_job_analysis_evals(
            cases_path=CASES_PATH,
            profile_path=PROFILE_PATH,
            use_llm=False,
        )
