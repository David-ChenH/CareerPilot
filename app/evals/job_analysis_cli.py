from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evals.job_analysis import JobAnalysisEvalReport, run_job_analysis_evals


DEFAULT_CASES_PATH = Path("evals/job_analysis/cases.yaml")
DEFAULT_PROFILE_PATH = Path("evals/profiles/backend_ai_platform.yaml")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CareerPilot job-analysis quality evals.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH, help="Path to job-analysis eval cases.")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH, help="Path to eval profile YAML.")
    parser.add_argument("--llm", action="store_true", help="Run the required LLM parser/scorer/guidance workflow.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON report.")
    args = parser.parse_args()

    if not args.llm:
        parser.error("job-analysis quality evals require --llm; deterministic fallback scoring has been removed")
    report = run_job_analysis_evals(cases_path=args.cases, profile_path=args.profile, use_llm=True)
    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        _print_human_report(report)
    return 0 if report.failed_cases == 0 else 1


def _print_human_report(report: JobAnalysisEvalReport) -> None:
    mode = "LLM"
    print(f"CareerPilot job-analysis evals ({mode})")
    print(f"Cases: {report.passed_cases}/{report.total_cases} passed")
    print(f"Profile: {report.profile_path}")
    print("")
    for result in report.results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.case_id}: {result.name}")
        print(
            f"  score={result.score} priority={result.priority} "
            f"recommendation={result.recommendation or 'n/a'} "
            f"parser={result.parser_used} scorer={result.scorer_used} guidance={result.guidance_used}"
        )
        for assertion in result.assertions:
            if not assertion.passed:
                print(f"  - {assertion.name}: expected {assertion.expected}; actual {assertion.actual}")
        print("")


if __name__ == "__main__":
    raise SystemExit(main())
