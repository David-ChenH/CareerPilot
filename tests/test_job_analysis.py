import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from app.agents.action_registry import ActionRegistry
from app.artifacts import PROFILE_PROPOSAL_WORKFLOW_VERSION, artifact_provenance
from app.agents.coordinator import (
    AnalysisChatRequest,
    AssistantChatRequest,
    AssistantFocus,
    GlobalChatRequest,
    JobAnalysisRequest,
    JobChatRequest,
    JobSearchCoordinator,
)
from app.db.models import AgentTaskStatus, AgentTaskType, ApplicationStatus, ApplicationType, JobRecord, ProfileProposal, ResumeVersion
from app.db.repository import JobRepository
from app.memory.profile_store import ProfileStore
from app.tools.job_parser import ParsedJob, parse_job_description
from app.tools.job_fetcher import _ReadableHTMLParser
from app.tools.job_extraction import ExtractedJobPosting, sections_from_lines
from app.extraction_overrides.career_pages import CareerPageExtractionOverrideRegistry
from app.tools.browser_job_fetcher import (
    BrowserJobPageFetchError,
    _extract_job_content,
    _maybe_validate_semantically,
    _score_content_candidate,
)
from app.tools.content_root_strategy import (
    ContentRootSemanticValidation,
    ContentRootStrategy,
    ContentRootStrategySource,
    validate_content_root,
)
from app.tools.learned_selector_store import LearnedSelectorStore
from app.tools.prep_planner import generate_prep_plan, parse_prep_plan_text
from app.tools.resume_generator import generate_resume_artifact, generate_resume_pdf
from app.tools.analysis_feedback import record_analysis_feedback
from app.tools.llm_job_parser import (
    CHUNK_CHARS,
    LLMParsedJob,
    MAX_CHUNKS,
    MAX_STRUCTURE_ARTIFACT_CHARS,
    _structure_artifact_json,
    _to_parsed_job,
    select_job_chunks,
)
from app.tools.llm_job_scorer import (
    LLMFitEvidence,
    LLMJobScorerUnavailable,
    _filter_grounded_items,
    _ground_evidence,
    _partition_hard_gaps,
    score_job_fit_with_llm,
)
from app.tools.llm_fit_validator import AnalysisValidationIssue, AnalysisValidationReport, LLMFitValidationUnavailable
from app.tools.llm_job_guidance import JobApplicationGuidance, _dedupe_text
from app.tools.scoring import JobFit
from app.tools.text_budget import MAX_JOB_ANALYSIS_CHARS, compact_job_text


class _FakeLocator:
    def __init__(self, texts: list[str], headings: list[str] | None = None) -> None:
        self.texts = texts
        self.headings = headings or ["Responsibilities", "Qualifications"]
        self.index = 0

    def count(self) -> int:
        return len(self.texts)

    def nth(self, index: int):
        locator = _FakeLocator(self.texts, self.headings)
        locator.index = index
        return locator

    def inner_text(self, timeout: int) -> str:
        del timeout
        return self.texts[self.index]

    def locator(self, _selector: str):
        return _FakeHeadingLocator(self.headings)


class _FakeHeadingLocator:
    def __init__(self, headings: list[str]) -> None:
        self.headings = headings

    def all_inner_texts(self) -> list[str]:
        return self.headings


class _FakePage:
    def __init__(self, selectors: dict[str, list[str]]) -> None:
        self.selectors = selectors

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self.selectors.get(selector, []))


def _job_text(label: str) -> str:
    return (
        f"{label} Senior Backend Engineer\nAbout the job\nBuild distributed backend services and reliable APIs. "
        "Responsibilities\nOwn architecture, implementation, and production operations. "
        "Qualifications\nExperience with Python, Kubernetes, and distributed systems. "
        "Preferred Qualifications\nExperience with workflow orchestration and cloud infrastructure. "
        "You will partner with product and engineering teams, improve service reliability, review architecture, "
        "design scalable APIs, operate production systems, and deliver customer-facing platform capabilities. "
        "The team owns distributed backend services that support critical workflows across the business."
    )


def _content_root_strategy(url: str, selector: str) -> ContentRootStrategy:
    return ContentRootStrategy(
        domain=url.split("/")[2],
        content_selector=selector,
        source=ContentRootStrategySource.BOUNDED_DISCOVERY,
        validation=validate_content_root(_job_text("Candidate")),
    )


@pytest.fixture(autouse=True)
def fake_semantic_scorer(monkeypatch) -> None:
    def evaluate(profile: dict, job: ParsedJob) -> JobFit:
        del profile
        skills = {skill.lower() for skill in job.skills}
        matches = []
        if "python" in skills:
            matches.append("Python programming")
        if "java" in skills:
            matches.append("Java programming")
        if "cloud" in skills:
            matches.append("Cloud infrastructure")
        if "workflow orchestration" in skills:
            matches.append("Workflow orchestration")
        if "api" in skills:
            matches.append("API and service design")
        if "distributed systems" in skills:
            matches.append("Distributed systems")
        return JobFit(
            score=82,
            priority="high",
            strong_matches=matches,
            gaps=[],
            concerns=[],
            summary="Test semantic evaluator found a strong role fit.",
            score_components={
                "role_alignment": 8,
                "skill_match": 8,
                "career_transition": 8,
                "seniority_fit": 8,
                "learning_roi": 8,
            },
            recommendation="apply",
        )

    monkeypatch.setattr("app.agents.coordinator.score_job_fit_with_llm", evaluate)
    monkeypatch.setattr(
        "app.agents.coordinator.validate_fit_with_llm",
        lambda profile, job, fit: AnalysisValidationReport(status="pass", summary="Valid fit."),
    )


def test_analyze_high_fit_ai_platform_job(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.analyze(
        JobAnalysisRequest(
            source_url="https://example.com/jobs/ai-platform-backend",
            use_llm=False,
            use_llm_guidance=False,
            description="""
            Senior Backend Engineer, AI Platform
            Company: Example AI
            Location: Remote

            Build backend APIs and distributed workflow orchestration for LLM agent systems.
            Experience with Python, cloud services, serverless systems, workflow orchestration, Kubernetes, and vector database systems preferred.
            """,
        )
    )

    assert response.fit.priority in {"high", "medium"}
    assert response.fit.score >= 65
    assert response.parser_used == "deterministic"
    assert response.parser_warning is None
    assert response.scorer_used == "llm"
    assert response.guidance_used == "disabled"
    assert response.guidance_warning is None
    assert response.guidance.prep_plan == []
    assert "python" in response.parsed_job.skills
    assert response.saved_job is not None
    assert response.saved_job.source_url == "https://example.com/jobs/ai-platform-backend"


def test_profile_store_applies_updates_and_writes_audit(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.local.yaml"
    audit_path = tmp_path / "profile_audit.jsonl"
    store = ProfileStore(path=profile_path, audit_path=audit_path)

    updated = store.apply_updates(
        {
            "technical_strengths": ["Java", "Python"],
            "learning_goals": ["Kubernetes"],
        },
        source="test",
    )

    assert "Java" in updated["technical_strengths"]
    assert "Kubernetes" in updated["learning_goals"]
    assert profile_path.exists()
    assert audit_path.exists()
    assert '"source": "test"' in audit_path.read_text(encoding="utf-8")
    assert '"profile_snapshot"' in audit_path.read_text(encoding="utf-8")


def test_analysis_feedback_is_recorded_as_jsonl(tmp_path: Path) -> None:
    feedback_path = tmp_path / "analysis_feedback.jsonl"
    record = record_analysis_feedback(
        feedback_type="missing_gap",
        note="Should mention Kubernetes.",
        source_url="https://example.com/job",
        analysis={
            "parsed_job": {"title": "Senior Backend Engineer", "company": "Example AI"},
            "fit": {"score": 82, "priority": "high", "recommendation": "apply"},
        },
        path=feedback_path,
    )

    content = feedback_path.read_text(encoding="utf-8")
    assert record["feedback_type"] == "missing_gap"
    assert "Should mention Kubernetes." in content
    assert "Senior Backend Engineer" in content


def test_agent_task_lifecycle_is_persisted(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    task = repository.create_agent_task(
        task_type=AgentTaskType.JOB_LINK_INGEST,
        task_input={"url": "https://example.com/job"},
        task_id="task-1",
    )

    repository.update_agent_task(task.id, status=AgentTaskStatus.RUNNING)
    repository.start_agent_task_step(task.id, "fetch_job", "Fetch readable text.")
    repository.complete_agent_task_step(task.id, "fetch_job", "Fetched 1200 characters.")
    repository.update_agent_task(
        task.id,
        status=AgentTaskStatus.COMPLETED,
        artifacts={"saved_job": {"id": 1, "title": "Senior Backend Engineer"}},
    )

    persisted = repository.get_agent_task(task.id)

    assert persisted is not None
    assert persisted.status == AgentTaskStatus.COMPLETED
    assert persisted.input["url"] == "https://example.com/job"
    assert persisted.steps[0].name == "fetch_job"
    assert persisted.steps[0].status == "completed"
    assert persisted.artifacts["saved_job"]["title"] == "Senior Backend Engineer"


def test_action_registry_detects_job_url_ingestion_intent() -> None:
    action = ActionRegistry().detect_from_message("Please save and analyze this job https://example.com/jobs/123.")

    assert action is not None
    assert action.name == "ingest_job_from_url"
    assert action.parameters["url"] == "https://example.com/jobs/123"
    assert action.parameters["save"] is True


def test_action_registry_ignores_unrelated_urls() -> None:
    action = ActionRegistry().detect_from_message("Can you summarize https://example.com/docs for me?")

    assert action is None


def test_job_text_compaction_keeps_analysis_under_budget() -> None:
    huge_description = "\n".join(
        [
            "Microsoft Careers",
            *["Search result filler"] * 20_000,
            "Responsibilities",
            "Build distributed backend services for developer productivity.",
            "Qualifications",
            "Experience with Kubernetes, Java, Python, and distributed systems.",
        ]
    )

    compacted = compact_job_text(huge_description)

    assert compacted.was_compacted is True
    assert compacted.original_length > compacted.compacted_length
    assert len(compacted.text) <= MAX_JOB_ANALYSIS_CHARS
    assert "Responsibilities" in compacted.text
    assert "Kubernetes" in compacted.text


def test_chunk_selector_prioritizes_job_signal_sections() -> None:
    huge_description = "\n".join(
        [
            "Microsoft Careers",
            *["Search result filler"] * 10_000,
            "Responsibilities",
            "Build distributed backend services for developer productivity.",
            "Required Qualifications",
            "Experience with Kubernetes, Java, Python, and distributed systems.",
            *["Footer filler"] * 5_000,
        ]
    )

    chunks = select_job_chunks(huge_description)
    combined = "\n".join(chunks)

    assert 1 <= len(chunks) <= MAX_CHUNKS
    assert all(len(chunk) <= CHUNK_CHARS for chunk in chunks)
    assert "Responsibilities" in combined
    assert "Kubernetes" in combined


def test_duplicate_job_is_not_saved_twice(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )
    request = JobAnalysisRequest(
        use_llm=False,
        use_llm_guidance=False,
        description="""
        Senior Backend Engineer
        Company: Example AI
        Build Python backend services on cloud infrastructure.
        """
    )

    first = coordinator.analyze(request)
    second = coordinator.analyze(request)

    assert first.saved_job is not None
    assert second.saved_job is not None
    assert first.saved_job.id == second.saved_job.id
    assert len(coordinator.repository.list_jobs()) == 1


def test_saved_job_is_classified_as_internal_transfer_for_same_company(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.local.yaml"
    profile_path.write_text(
        """
current_role:
  title: "Software Development Engineer"
  company: "Example Cloud"
technical_strengths:
  - "Python"
target_roles:
  - "Backend engineer"
avoid: []
""",
        encoding="utf-8",
    )
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(path=profile_path),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.analyze(
        JobAnalysisRequest(
            use_llm=False,
            use_llm_guidance=False,
            source_url="https://careers.example-cloud.test/jobs/123/software-development-engineer",
            description="Software Development Engineer\nCompany: Example Cloud\nBuild backend systems.",
        )
    )

    assert response.saved_job is not None
    assert response.saved_job.application_type == ApplicationType.INTERNAL_TRANSFER


def test_saved_job_is_classified_as_external_for_different_company(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.local.yaml"
    profile_path.write_text(
        """
current_role:
  title: "Software Development Engineer"
  company: "Example Cloud"
technical_strengths:
  - "Python"
target_roles:
  - "Backend engineer"
avoid: []
""",
        encoding="utf-8",
    )
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(path=profile_path),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.analyze(
        JobAnalysisRequest(
            use_llm=False,
            use_llm_guidance=False,
            source_url="https://www.metacareers.com/jobs/123",
            description="Senior Backend Engineer\nCompany: Meta\nBuild backend systems.",
        )
    )

    assert response.saved_job is not None
    assert response.saved_job.application_type == ApplicationType.EXTERNAL_APPLICATION


def test_analysis_can_preview_without_saving_then_save_explicitly(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    analysis = coordinator.analyze(
        JobAnalysisRequest(
            save=False,
            use_llm=False,
            use_llm_guidance=False,
            source_url="https://example.com/jobs/preview",
            description="Senior Backend Engineer\nCompany: Example AI\nBuild Python backend services.",
        )
    )

    assert analysis.saved_job is None
    assert coordinator.repository.list_jobs() == []

    saved_job = coordinator.save_analysis(analysis, source_url="https://example.com/jobs/preview")

    assert saved_job.id is not None
    assert saved_job.source_url == "https://example.com/jobs/preview"
    assert len(coordinator.repository.list_jobs()) == 1


def test_duplicate_job_is_detected_by_source_url(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    first = coordinator.analyze(
        JobAnalysisRequest(
            source_url="https://example.com/jobs/123",
            use_llm=False,
            use_llm_guidance=False,
            description="Senior Backend Engineer\nCompany: Example AI\nBuild Python backend services.",
        )
    )
    second = coordinator.analyze(
        JobAnalysisRequest(
            source_url="https://example.com/jobs/123",
            use_llm=False,
            use_llm_guidance=False,
            description="Senior Backend Engineer\nCompany: Example AI\nUpdated wording for same role.",
        )
    )

    assert first.saved_job is not None
    assert second.saved_job is not None
    assert first.saved_job.id == second.saved_job.id
    assert len(coordinator.repository.list_jobs()) == 1


def test_delete_saved_job(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.analyze(
        JobAnalysisRequest(
            use_llm=False,
            use_llm_guidance=False,
            description="Senior Backend Engineer\nCompany: Example AI\nBuild Python backend services.",
        )
    )

    assert response.saved_job is not None
    assert coordinator.repository.delete_job(response.saved_job.id)
    assert coordinator.repository.list_jobs() == []


def test_meta_careers_url_infers_company_and_ignores_generic_page_title(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.analyze(
        JobAnalysisRequest(
            source_url="https://www.metacareers.com/profile/job_details/1436181490732782",
            page_title="Meta Careers",
            use_llm=False,
            use_llm_guidance=False,
            description="""
            Meta Careers
            Software Engineer, AI Platform
            Reality Labs
            Build Python services for LLM infrastructure and distributed backend systems.
            """,
        )
    )

    assert response.parsed_job.company == "Meta"
    assert response.parsed_job.title == "Software Engineer, AI Platform"
    assert response.saved_job is not None
    assert response.saved_job.company == "Meta"


def test_llm_parser_falls_back_without_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOB_AGENT_DISABLE_DOTENV", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.analyze(
        JobAnalysisRequest(
            description="Senior Backend Engineer\nCompany: Example AI\nBuild Python backend services.",
        )
    )

    assert response.parser_used == "deterministic"
    assert response.parser_warning == "OPENAI_API_KEY is not set."
    assert response.scorer_used == "llm"
    assert response.guidance_used == "unavailable"
    assert response.guidance_warning == "OPENAI_API_KEY is not set."


def test_fit_validation_pass_leaves_fit_unchanged(tmp_path: Path, monkeypatch) -> None:
    report = AnalysisValidationReport(status="pass", summary="Looks grounded.")
    monkeypatch.setattr("app.agents.coordinator.validate_fit_with_llm", lambda profile, job, fit: report)

    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.analyze(
        JobAnalysisRequest(
            description="Senior Backend Engineer\nCompany: Example AI\nBuild Java backend services.",
            use_llm=False,
            use_llm_guidance=False,
        )
    )

    assert response.fit.summary == "Test semantic evaluator found a strong role fit."
    assert response.validation_report == report
    assert response.validation_used == "llm"
    assert response.validation_warning is None


def test_fit_validation_repair_runs_once(tmp_path: Path, monkeypatch) -> None:
    calls = {"validate": 0, "repair": 0}
    repair_required = AnalysisValidationReport(
        status="repair_required",
        summary="C++ is incorrectly treated as a barrier.",
        issues=[
            AnalysisValidationIssue(
                type="alternative_requirement_conflict",
                severity="high",
                field="fit.growth_areas",
                claim="C++ is a barrier.",
                evidence="either Java, Scala or C++",
                repair_instruction="Remove C++ as a barrier because Java satisfies the alternative.",
            )
        ],
    )
    pass_report = AnalysisValidationReport(status="pass", summary="Repaired fit is valid.")

    def validate(profile, job, fit):
        del profile, job, fit
        calls["validate"] += 1
        return repair_required if calls["validate"] == 1 else pass_report

    def repair(profile, job, fit, validation_report):
        del profile, job, validation_report
        calls["repair"] += 1
        return fit.model_copy(update={"growth_areas": [], "summary": "Repaired summary."})

    monkeypatch.setattr("app.agents.coordinator.validate_fit_with_llm", validate)
    monkeypatch.setattr("app.agents.coordinator.repair_fit_with_llm", repair)

    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.analyze(
        JobAnalysisRequest(
            description="Senior Backend Engineer\nCompany: Example AI\nBuild Java backend services.",
            use_llm=False,
            use_llm_guidance=False,
        )
    )

    assert calls == {"validate": 2, "repair": 1}
    assert response.fit.summary == "Repaired summary."
    assert response.validation_report == pass_report
    assert response.validation_used == "llm_repaired"
    assert response.validation_warning is None


def test_fit_validation_unresolved_repair_records_warning(tmp_path: Path, monkeypatch) -> None:
    repair_required = AnalysisValidationReport(status="repair_required", summary="Needs repair.")

    monkeypatch.setattr("app.agents.coordinator.validate_fit_with_llm", lambda profile, job, fit: repair_required)
    monkeypatch.setattr("app.agents.coordinator.repair_fit_with_llm", lambda profile, job, fit, validation_report: fit)

    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.analyze(
        JobAnalysisRequest(
            description="Senior Backend Engineer\nCompany: Example AI\nBuild Java backend services.",
            use_llm=False,
            use_llm_guidance=False,
        )
    )

    assert response.validation_used == "llm_repair_unresolved"
    assert response.validation_warning == "Fit validation still returned repair_required after one repair pass."


def test_fit_validation_unavailable_records_warning(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agents.coordinator.validate_fit_with_llm",
        lambda profile, job, fit: (_ for _ in ()).throw(LLMFitValidationUnavailable("validator down")),
    )

    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.analyze(
        JobAnalysisRequest(
            description="Senior Backend Engineer\nCompany: Example AI\nBuild Java backend services.",
            use_llm=False,
            use_llm_guidance=False,
        )
    )

    assert response.validation_report is None
    assert response.validation_used == "unavailable"
    assert response.validation_warning == "validator down"


def test_semantic_scorer_fails_explicitly_without_api_key(monkeypatch) -> None:
    monkeypatch.setenv("JOB_AGENT_DISABLE_DOTENV", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(LLMJobScorerUnavailable, match="OPENAI_API_KEY is not set"):
        score_job_fit_with_llm(
            profile={"technical_strengths": ["Python"]},
            job=ParsedJob(title="Backend Engineer", description="Build Python backend services."),
        )


def test_llm_parser_result_is_used_when_available(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    with patch("app.agents.coordinator.parse_job_with_llm") as parse_job_with_llm:
        parse_job_with_llm.return_value = coordinator.analyze(
            JobAnalysisRequest(
                description="Principal AI Platform Engineer\nCompany: Example AI",
                save=False,
                use_llm=False,
                use_llm_guidance=False,
            )
        ).parsed_job.model_copy(update={"company": "LLM Company"})

        response = coordinator.analyze(
            JobAnalysisRequest(
                description="Principal AI Platform Engineer\nCompany: Example AI",
                use_llm_guidance=False,
            )
        )

    assert response.parser_used == "llm"
    assert response.parser_warning is None
    assert response.parsed_job.company == "LLM Company"


def test_llm_scorer_result_is_used_when_available(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    with patch("app.agents.coordinator.score_job_fit_with_llm") as score_job_fit_with_llm:
        score_job_fit_with_llm.return_value = JobFit(
            score=88,
            priority="high",
            strong_matches=["Platform engineering", "Career transition bridge"],
            gaps=["Kubernetes depth"],
            concerns=[],
            summary="Strong semantic fit for the user's transition goal.",
            score_components={
                "role_alignment": 9,
                "skill_match": 7,
                "career_transition": 10,
                "seniority_fit": 8,
                "learning_roi": 9,
            },
            recommendation="apply",
            transition_notes=["Good bridge from backend systems into AI platform work."],
        )

        response = coordinator.analyze(
            JobAnalysisRequest(
                description="Senior AI Platform Engineer\nCompany: Example AI\nBuild agent workflow infrastructure.",
                use_llm=False,
                use_llm_guidance=False,
            )
        )

    assert response.scorer_used == "llm"
    assert response.fit.score == 88
    assert response.fit.recommendation == "apply"
    assert response.fit.score_components["career_transition"] == 10
    assert response.fit.gaps == ["Kubernetes depth"]


def test_llm_scorer_does_not_inherit_baseline_gaps_when_semantic_gaps_are_empty(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    with patch("app.agents.coordinator.score_job_fit_with_llm") as score_job_fit_with_llm:
        score_job_fit_with_llm.return_value = JobFit(
            score=82,
            priority="high",
            strong_matches=["Distributed systems"],
            gaps=[],
            concerns=[],
            summary="Strong semantic fit; no critical gaps identified by the evaluator.",
            score_components={
                "role_alignment": 8,
                "skill_match": 8,
                "career_transition": 8,
                "seniority_fit": 8,
                "learning_roi": 7,
            },
            recommendation="apply",
            transition_notes=[],
        )

        response = coordinator.analyze(
            JobAnalysisRequest(
                description="""
                Senior Platform Engineer
                Company: Example Infra
                Build Kubernetes services and vector database infrastructure.
                """,
                use_llm=False,
                use_llm_guidance=False,
            )
        )

    assert response.scorer_used == "llm"
    assert response.fit.gaps == []


def test_rag_is_not_detected_inside_unrelated_words(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.analyze(
        JobAnalysisRequest(
            use_llm=False,
            use_llm_guidance=False,
            description="""
            Senior Storage Platform Engineer
            Company: Example Infra

            Build backend services for storage infrastructure, data durability,
            and distributed systems operations.
            """,
        )
    )

    assert "rag" not in response.parsed_job.skills
    assert "Retrieval augmented generation" not in response.fit.gaps


def test_deterministic_fallback_extracts_skills_but_does_not_claim_skill_gaps(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.analyze(
        JobAnalysisRequest(
            use_llm=False,
            use_llm_guidance=False,
            source_url="https://www.amazon.jobs/en-gb/jobs/10421792/software-development-engineer",
            description="""
            Software Development Engineer
            Company: Example Commerce

            Build distributed streaming systems using Apache Flink and operate
            containerized services on Kubernetes and Amazon Elastic Kubernetes Service.
            """,
        )
    )

    assert "eks" in response.parsed_job.skills
    assert "flink" in response.parsed_job.skills
    assert "kubernetes" in response.parsed_job.skills
    assert response.fit.gaps == []
    assert "Main learning gaps" not in response.fit.summary


def test_deterministic_parser_does_not_treat_generic_container_as_docker_gap(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.analyze(
        JobAnalysisRequest(
            use_llm=False,
            use_llm_guidance=False,
            description="""
            Software Engineer
            Company: Example
            Build Java backend systems. This page has a generic UI container element.
            Required Qualifications: Java, distributed systems, cloud services.
            """,
        )
    )

    assert "java" in response.parsed_job.skills
    assert "docker" not in response.parsed_job.skills
    assert "Docker/containerization" not in response.fit.gaps
    assert "Java programming" in response.fit.strong_matches


def test_llm_gap_filter_removes_unsupported_generic_gaps() -> None:
    job = ParsedJob(
        title="Software Engineer",
        company="Microsoft",
        description="Required Qualifications: Java, distributed systems, cloud services.",
        skills=["java", "distributed systems", "cloud"],
        requirements=["Java", "distributed systems", "cloud services"],
    )
    profile = {"technical_strengths": ["Java", "Python", "AWS"]}

    filtered = _filter_grounded_items(
        ["Docker/containerization", "C++ and C# depth", "Java distributed systems"],
        job,
        profile,
    )

    assert "Docker/containerization" not in filtered
    assert "C++ and C# depth" not in filtered
    assert "Java distributed systems" not in filtered


def test_llm_gap_filter_does_not_treat_accepted_language_alternatives_as_separate_gaps() -> None:
    job = ParsedJob(
        title="Senior Software Engineer - Browser Platform",
        company="Microsoft",
        description=(
            "Technical engineering experience with coding in languages including, but not limited to, "
            "C, C++, C#, Java, or Python."
        ),
        skills=["c++", "c#", "java", "python"],
        requirements=["Coding in languages including, but not limited to, C, C++, C#, Java, or Python."],
    )
    profile = {"technical_strengths": ["Java", "Python", "AWS"]}

    filtered = _filter_grounded_items(["Direct experience with C/C++/C#"], job, profile)

    assert filtered == []


def test_llm_gap_filter_handles_either_java_scala_or_cpp_alternatives() -> None:
    job = ParsedJob(
        title="Senior Software Engineer - Distributed Data Systems",
        company="Databricks",
        description="What we look for: 5+ years of production level experience in either Java, Scala or C++.",
        skills=["java", "scala", "c++", "distributed systems"],
        requirements=["5+ years of production level experience in either Java, Scala or C++."],
        accepted_skill_alternatives=["5+ years of production level experience in either Java, Scala or C++."],
    )
    profile = {"technical_strengths": ["Java", "Python", "AWS", "distributed systems"]}

    filtered = _filter_grounded_items(
        [
            "C++ is highlighted as a required skill, but not mentioned in the profile.",
            "C++ proficiency for production environments.",
            "Scala production experience.",
        ],
        job,
        profile,
    )

    assert filtered == []


def test_deterministic_parser_does_not_classify_accepted_language_alternatives() -> None:
    parsed = parse_job_description(
        "Coding experience in languages including, but not limited to, C, C++, C#, Java, or Python."
    )

    assert parsed.accepted_skill_alternatives == []


def test_llm_parser_output_owns_accepted_language_alternatives() -> None:
    deterministic = parse_job_description(
        "Senior Software Engineer\nCompany: Databricks\n"
        "What we look for: 5+ years of production level experience in either Java, Scala or C++."
    )
    parsed = _to_parsed_job(
        LLMParsedJob(
            title="Senior Software Engineer",
            company="Databricks",
            skills=["Java", "Scala", "C++"],
            required_skills=["Java", "Scala", "C++"],
            requirements=["5+ years of production level experience in either Java, Scala or C++."],
            accepted_skill_alternatives=[
                "5+ years of production level experience in either Java, Scala or C++."
            ],
        ),
        deterministic,
        deterministic.description,
    )

    assert parsed.accepted_skill_alternatives == [
        "5+ years of production level experience in either Java, Scala or C++."
    ]
    assert parsed.required_skills == []


def test_llm_gap_partition_keeps_required_items_and_downgrades_preferred_items() -> None:
    job = ParsedJob(
        title="Senior Software Engineer",
        company="Example",
        description="Required: Kubernetes. Preferred: experience evaluating and training ML models.",
        required_skills=["Kubernetes"],
        preferred_qualifications=["Experience evaluating and training ML models."],
    )

    hard_gaps, growth_areas = _partition_hard_gaps(
        ["Kubernetes depth", "ML evaluation and training mechanisms"],
        job,
    )

    assert hard_gaps == ["Kubernetes depth"]
    assert growth_areas == ["ML evaluation and training mechanisms"]


def test_llm_gap_partition_downgrades_ambiguous_qualification_items() -> None:
    job = ParsedJob(
        title="Senior Software Engineer",
        company="Microsoft",
        description=(
            "Bachelor's Degree in Computer Science or related technical field AND 4+ years technical engineering experience. "
            "Master's Degree in Computer Science or related technical field AND 6+ years technical engineering experience. "
            "Bachelor's Degree in Computer Science or related technical field AND 8+ years technical engineering experience "
            "OR equivalent experience."
        ),
        requirements=["Bachelor's Degree and 4+ years technical engineering experience."],
        ambiguous_qualifications=[
            "Master's Degree and 6+ years technical engineering experience.",
            "Bachelor's Degree and 8+ years technical engineering experience OR equivalent experience.",
        ],
    )

    hard_gaps, growth_areas = _partition_hard_gaps(["8+ years technical engineering experience"], job)

    assert hard_gaps == []
    assert growth_areas == ["8+ years technical engineering experience"]


def test_llm_evidence_filter_requires_job_grounding() -> None:
    job = ParsedJob(
        title="Software Engineer",
        company="Microsoft",
        description="Required Qualifications: Java, distributed systems, cloud services.",
        skills=["java", "distributed systems", "cloud"],
        requirements=["Java", "distributed systems", "cloud services"],
    )
    profile = {"technical_strengths": ["Java", "Python", "AWS"]}

    evidence = _ground_evidence(
        [
            LLMFitEvidence(
                claim="Java distributed systems overlap",
                evidence_from_job="Required Qualifications: Java, distributed systems.",
                profile_signal="Technical strengths include Java.",
                severity="positive",
                confidence="high",
            ),
            LLMFitEvidence(
                claim="Docker gap",
                evidence_from_job="The role requires Docker.",
                profile_signal="Docker is not listed in the profile.",
                severity="useful",
                confidence="medium",
            ),
        ],
        job,
        profile,
        allowed_claims=None,
    )

    assert [item.claim for item in evidence] == ["Java distributed systems overlap"]
    assert evidence[0].evidence_from_job == "Required Qualifications: Java, distributed systems."
    assert evidence[0].profile_source_path == "technical_strengths[0]"
    assert evidence[0].profile_evidence == "Java"


def test_llm_evidence_filter_rejects_unsupported_language_blocker() -> None:
    job = ParsedJob(
        title="Full stack Software Engineer",
        company="Microsoft",
        description="Experience with React, Angular, or Vue. Experience working with Kubernetes and Containers.",
        skills=["kubernetes"],
        requirements=["Experience with React, Angular, or Vue.", "Experience working with Kubernetes and Containers."],
    )

    evidence = _ground_evidence(
        [
            LLMFitEvidence(
                claim="C# and JavaScript proficiency gap",
                evidence_from_job="Job requires proficiency in C# and JavaScript.",
                profile_signal="C# is not listed in the profile.",
                severity="blocker",
                confidence="medium",
            )
        ],
        job,
        {"technical_strengths": ["Java", "Python", "AWS"]},
        allowed_claims=None,
    )

    assert evidence == []


def test_llm_evidence_uses_requested_profile_source_path_when_supported() -> None:
    job = ParsedJob(
        title="Backend Platform Engineer",
        company="Example",
        description="Build distributed backend APIs for cloud services.",
        skills=["distributed systems", "backend"],
        requirements=["distributed backend APIs"],
    )
    profile = {
        "experience_highlights": [
            "Designed public pricing APIs and distributed control plane services at AWS.",
        ],
        "technical_strengths": ["Java", "Python"],
    }

    evidence = _ground_evidence(
        [
            LLMFitEvidence(
                claim="Distributed backend API experience aligns with the role",
                evidence_from_job="Build distributed backend APIs for cloud services.",
                profile_signal="Designed public pricing APIs and distributed control plane services at AWS.",
                profile_source_path="experience_highlights[0]",
                severity="positive",
                confidence="high",
            )
        ],
        job,
        profile,
        allowed_claims=None,
    )

    assert len(evidence) == 1
    assert evidence[0].profile_source_path == "experience_highlights[0]"
    assert evidence[0].profile_evidence == "Designed public pricing APIs and distributed control plane services at AWS."
    assert evidence[0].confidence == "high"


def test_llm_evidence_marks_unsupported_profile_signal_low_confidence() -> None:
    job = ParsedJob(
        title="Backend Platform Engineer",
        company="Example",
        description="Build distributed backend APIs for cloud services.",
        skills=["distributed systems", "backend"],
        requirements=["distributed backend APIs"],
    )

    evidence = _ground_evidence(
        [
            LLMFitEvidence(
                claim="Backend API experience aligns with the role",
                evidence_from_job="Build distributed backend APIs for cloud services.",
                profile_signal="Profile shows deep Rust compiler experience.",
                severity="positive",
                confidence="high",
            )
        ],
        job,
        {"technical_strengths": ["Java", "Python"]},
        allowed_claims=None,
    )

    assert len(evidence) == 1
    assert evidence[0].profile_source_path is None
    assert evidence[0].profile_evidence is None
    assert evidence[0].confidence == "low"


def test_html_fetcher_prefers_structured_job_posting_json_ld() -> None:
    parser = _ReadableHTMLParser()
    parser.feed(
        """
        <html>
          <head>
            <title>Careers portal</title>
            <script type="application/ld+json">
              {
                "@type": "JobPosting",
                "title": "Senior Software Engineer",
                "description": "Build distributed backend services with Kubernetes.",
                "hiringOrganization": {"name": "Microsoft"},
                "jobLocation": {"address": {"addressLocality": "Redmond", "addressRegion": "WA"}}
              }
            </script>
          </head>
          <body>Navigation text and unrelated portal chrome.</body>
        </html>
        """
    )

    assert parser.job_posting_title == "Senior Software Engineer"
    assert parser.job_posting_text == "Senior Software Engineer\nMicrosoft\nRedmond, WA\nBuild distributed backend services with Kubernetes."
    assert parser.job_posting_needs_browser_render is False


def test_html_fetcher_preserves_structured_description_headings() -> None:
    parser = _ReadableHTMLParser()
    parser.feed(
        """
        <script type="application/ld+json">
          {
            "@type": "JobPosting",
            "title": "Senior Software Engineer",
            "description": "<h2>Required Qualifications</h2><p>Bachelor's degree and 4+ years experience.</p><h2>Preferred Qualifications</h2><p>Master's degree and 6+ years experience.</p>"
          }
        </script>
        """
    )

    assert parser.job_posting_text == (
        "Senior Software Engineer\n"
        "Required Qualifications\n"
        "Bachelor's degree and 4+ years experience.\n"
        "Preferred Qualifications\n"
        "Master's degree and 6+ years experience."
    )
    assert parser.job_posting_needs_browser_render is False


def test_html_fetcher_flags_flattened_long_qualification_text_for_browser_render() -> None:
    parser = _ReadableHTMLParser()
    parser.feed(
        f"""
        <script type="application/ld+json">
          {{
            "@type": "JobPosting",
            "title": "Senior Software Engineer",
            "description": "Build platform services. {"Responsibilities and engineering impact. " * 15} Bachelor's Degree and 4+ years experience. Master's Degree and 6+ years experience. Preferred qualifications include distributed systems."
          }}
        </script>
        """
    )

    assert parser.job_posting_needs_browser_render is True


def test_extraction_artifact_preserves_unfamiliar_dom_heading_for_llm_classification() -> None:
    sections = sections_from_lines(
        "Shape the future\nBuild distributed services.\nWays to stand out\nExperience with Kubernetes.",
        source="browser_rendered",
        headings=["Shape the future", "Ways to stand out"],
    )
    posting = ExtractedJobPosting(
        metadata={"title": "Senior Backend Engineer", "company": "Example AI"},
        sections=sections,
        extraction_source="browser_rendered",
    )

    assert [section.heading for section in posting.sections] == ["Shape the future", "Ways to stand out"]
    assert posting.analysis_text("") == (
        "Senior Backend Engineer\n"
        "Example AI\n"
        "Shape the future\n"
        "Build distributed services.\n"
        "Ways to stand out\n"
        "Experience with Kubernetes."
    )


def test_structure_artifact_prompt_remains_valid_json_when_compacted() -> None:
    posting = ExtractedJobPosting(
        metadata={"title": "Senior Backend Engineer"},
        sections=sections_from_lines(
            "\n".join(["Qualifications", *(["Experience building distributed systems."] * 1_000)]),
            source="browser_rendered",
            headings=["Qualifications"],
        ),
        extraction_source="browser_rendered",
    )

    prompt_json = _structure_artifact_json(posting)

    assert len(prompt_json) <= MAX_STRUCTURE_ARTIFACT_CHARS
    assert json.loads(prompt_json)["sections"][0]["heading"] == "Qualifications"


def test_learned_selector_promotes_after_repeated_success(tmp_path: Path) -> None:
    store = LearnedSelectorStore(tmp_path / "selectors.json")
    url = "https://careers.example.com/jobs/123"

    first = store.record_success(_content_root_strategy(url, "main"))
    second = store.record_success(_content_root_strategy(url, "main"))

    assert first.status == "candidate"
    assert second.status == "promoted"
    assert second.validation is not None
    assert second.validation.passed is True
    assert store.get_promoted(url) == second


def test_learned_selector_does_not_promote_when_required_semantic_validation_is_unavailable(tmp_path: Path) -> None:
    store = LearnedSelectorStore(tmp_path / "selectors.json")
    url = "https://careers.example.com/jobs/123"
    store.record_success(_content_root_strategy(url, "main"))
    promotion_bound = _content_root_strategy(url, "main").model_copy(
        update={
            "semantic_validation": ContentRootSemanticValidation(
                required=True,
                attempted=False,
                error="OPENAI_API_KEY is not set.",
            )
        }
    )

    second = store.record_success(promotion_bound)

    assert second.successful_extractions == 2
    assert second.status == "candidate"
    assert store.get_promoted(url) is None


def test_learned_selector_promotes_when_required_semantic_validation_passes(tmp_path: Path) -> None:
    store = LearnedSelectorStore(tmp_path / "selectors.json")
    url = "https://careers.example.com/jobs/123"
    store.record_success(_content_root_strategy(url, "main"))
    promotion_bound = _content_root_strategy(url, "main").model_copy(
        update={
            "semantic_validation": ContentRootSemanticValidation(
                required=True,
                attempted=True,
                passed=True,
                confidence="high",
                is_single_complete_job_posting=True,
                reason="Contains one complete posting.",
            )
        }
    )

    second = store.record_success(promotion_bound)

    assert second.status == "promoted"
    assert second.semantic_validation is not None
    assert second.semantic_validation.passed is True


def test_learned_selector_returns_to_candidate_when_promoted_selector_drifts(tmp_path: Path) -> None:
    store = LearnedSelectorStore(tmp_path / "selectors.json")
    url = "https://careers.example.com/jobs/123"
    store.record_success(_content_root_strategy(url, "main"))
    store.record_success(_content_root_strategy(url, "main"))

    observation = store.record_failure(url, "main")

    assert observation is not None
    assert observation.status == "candidate"
    assert observation.failed_extractions == 1
    assert store.get_promoted(url) is None


def test_browser_content_candidate_prefers_job_text_over_navigation() -> None:
    job_text = (
        "About the job\nBuild distributed services.\nResponsibilities\nOwn backend APIs.\n"
        "Qualifications\nExperience with Python and Kubernetes.\nPreferred Qualifications\nApache Flink experience."
        "\nYou will design reliable distributed systems, review architecture, and improve production services."
    )

    assert _score_content_candidate(job_text) > _score_content_candidate("Search jobs Sign in Privacy Cookie settings")


def test_browser_extraction_prefers_promoted_learned_selector(tmp_path: Path) -> None:
    url = "https://apply.careers.microsoft.com/careers/job/123"
    store = LearnedSelectorStore(tmp_path / "selectors.json")
    store.record_success(_content_root_strategy(url, "article"))
    store.record_success(_content_root_strategy(url, "article"))
    page = _FakePage({"article": [_job_text("Learned")], "main": [_job_text("Override")]})

    strategy, text, _headings = _extract_job_content(
        page,
        url,
        store,
        CareerPageExtractionOverrideRegistry(),
    )

    assert strategy.source == "learned_observation"
    assert strategy.content_selector == "article"
    assert "Learned" in text


def test_browser_extraction_uses_reviewed_override_before_discovery(tmp_path: Path) -> None:
    url = "https://apply.careers.microsoft.com/careers/job/123"
    page = _FakePage({"main": [_job_text("Override")], "article": [_job_text("Discovery")]})

    strategy, text, _headings = _extract_job_content(
        page,
        url,
        LearnedSelectorStore(tmp_path / "selectors.json"),
        CareerPageExtractionOverrideRegistry(),
    )

    assert strategy.source == "reviewed_override"
    assert strategy.content_selector == "main"
    assert "Override" in text


def test_browser_extraction_demotes_stale_learned_selector_and_discovers_fallback(tmp_path: Path) -> None:
    url = "https://careers.example.com/jobs/123"
    store = LearnedSelectorStore(tmp_path / "selectors.json")
    store.record_success(_content_root_strategy(url, "article"))
    store.record_success(_content_root_strategy(url, "article"))
    page = _FakePage({"article": ["Sign in Privacy"], "main": [_job_text("Discovered")]})

    strategy, text, _headings = _extract_job_content(
        page,
        url,
        store,
        CareerPageExtractionOverrideRegistry(),
    )

    assert strategy.source == "bounded_discovery"
    assert strategy.content_selector == "main"
    assert "Discovered" in text
    assert store.get_promoted(url) is None


def test_browser_extraction_rejects_noisy_content_root(tmp_path: Path) -> None:
    page = _FakePage({"main": ["Search jobs Sign in Privacy Cookie settings"], "body": ["Search jobs"]})

    with pytest.raises(BrowserJobPageFetchError, match="readable content root"):
        _extract_job_content(
            page,
            "https://careers.example.com/jobs/123",
            LearnedSelectorStore(tmp_path / "selectors.json"),
            CareerPageExtractionOverrideRegistry(),
        )


def test_semantic_validation_is_required_for_new_selector(monkeypatch) -> None:
    strategy = _content_root_strategy("https://careers.example.com/jobs/123", "main")

    def validate(**kwargs):
        del kwargs
        return ContentRootSemanticValidation(
            required=True,
            attempted=True,
            passed=True,
            confidence="high",
            is_single_complete_job_posting=True,
            reason="Valid posting.",
        )

    monkeypatch.setattr("app.tools.browser_job_fetcher.validate_content_root_with_llm", validate)

    updated = _maybe_validate_semantically(strategy, _job_text("Valid"), ["Responsibilities"], None)

    assert updated.semantic_validation is not None
    assert updated.semantic_validation.required is True
    assert updated.semantic_validation.passed is True


def test_semantic_validation_unavailable_is_recorded_for_required_case(monkeypatch) -> None:
    strategy = _content_root_strategy("https://careers.example.com/jobs/123", "main")

    def validate(**kwargs):
        del kwargs
        from app.tools.llm_content_root_validator import LLMContentRootValidatorUnavailable

        raise LLMContentRootValidatorUnavailable("OPENAI_API_KEY is not set.")

    monkeypatch.setattr("app.tools.browser_job_fetcher.validate_content_root_with_llm", validate)

    updated = _maybe_validate_semantically(strategy, _job_text("Valid"), ["Responsibilities"], None)

    assert updated.semantic_validation is not None
    assert updated.semantic_validation.required is True
    assert updated.semantic_validation.attempted is False
    assert "OPENAI_API_KEY" in (updated.semantic_validation.error or "")


def test_guidance_dedupes_repeated_items() -> None:
    assert _dedupe_text(
        [
            "Role may include frontend-heavy work.",
            " Role may include frontend-heavy work. ",
            "Prepare distributed systems examples.",
        ]
    ) == [
        "Role may include frontend-heavy work.",
        "Prepare distributed systems examples.",
    ]


def test_guidance_evidence_uses_strict_named_groups_instead_of_free_form_map() -> None:
    schema = JobApplicationGuidance.model_json_schema()
    evidence_schema = schema["$defs"]["GuidanceEvidence"]

    assert set(evidence_schema["properties"]) == {
        "apply_reasoning",
        "prep_plan",
        "resume_guidance",
        "learning_plan",
        "interview_focus",
    }
    assert "additionalProperties" not in evidence_schema


def test_llm_guidance_result_is_used_when_available(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    with patch("app.agents.coordinator.generate_job_guidance_with_llm") as generate_guidance:
        generate_guidance.return_value = JobApplicationGuidance(
            apply_reasoning=["Strong role for AI platform transition."],
            prep_plan=["Review Kubernetes workload primitives.", "Prepare a workflow orchestration design story."],
            resume_guidance=["Lead with backend workflow ownership."],
            learning_plan=["Build a small queue-driven agent workflow."],
            interview_focus=["Distributed workflow design"],
        )

        response = coordinator.analyze(
            JobAnalysisRequest(
                description="Senior AI Platform Engineer\nCompany: Example AI\nBuild agent workflow infrastructure.",
                use_llm=False,
            )
        )

    assert response.guidance_used == "llm"
    assert response.guidance_warning is None
    assert response.guidance.prep_plan[0] == "Review Kubernetes workload primitives."
    assert response.prep_topics == response.guidance.prep_plan
    assert response.resume_emphasis == response.guidance.resume_guidance


def test_saved_job_persists_analysis_payload(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.analyze(
        JobAnalysisRequest(
            use_llm=False,
            use_llm_guidance=False,
            description="""
            Senior Backend Engineer, AI Platform
            Company: Example AI
            Build Python backend services for agent workflow infrastructure.
            """,
        )
    )

    assert response.saved_job is not None
    detail = coordinator.repository.get_job(response.saved_job.id)

    assert detail is not None
    assert detail.job.analysis is not None
    assert detail.analysis is not None
    assert detail.analysis["fit"]["score"] == response.fit.score
    assert detail.analysis["guidance"]["prep_plan"] == response.guidance.prep_plan
    assert detail.job.analysis_schema_version == 5
    assert detail.job.analysis_provenance is not None
    assert detail.job.analysis_provenance.generator == "llm"


def test_reanalysis_refreshes_existing_job_analysis_payload(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=repository,
    )
    description = """
    Senior Backend Engineer, AI Platform
    Company: Example AI
    Build Python backend services for agent workflow infrastructure.
    """
    old_job = repository.save_job(
        JobRecord(
            source_url="https://example.com/jobs/ai-platform-backend",
            title="Senior Backend Engineer",
            company="Example AI",
            description=description,
            skills=["Python"],
            fit_score=50,
            priority="medium",
            status=ApplicationStatus.APPLIED,
            analysis={"fit": {"score": 50}},
        )
    )

    response = coordinator.analyze(
        JobAnalysisRequest(
            use_llm=False,
            use_llm_guidance=False,
            source_url="https://example.com/jobs/ai-platform-backend",
            description=description,
        )
    )

    assert response.saved_job is not None
    assert response.saved_job.id == old_job.id
    assert response.saved_job.status == ApplicationStatus.APPLIED

    detail = repository.get_job(old_job.id)
    assert detail is not None
    assert detail.analysis is not None
    assert detail.analysis["parsed_job"]["title"] == response.parsed_job.title
    assert detail.analysis["fit"]["score"] == response.fit.score
    versions = repository.list_job_analysis_versions(old_job.id)
    assert len(versions) == 2
    assert versions[0]["analysis"]["fit"]["score"] == 50
    assert versions[1]["analysis"]["fit"]["score"] == response.fit.score
    assert versions[1]["schema_version"] == detail.job.analysis_schema_version


def test_explicit_analysis_update_preserves_application_state(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=repository,
    )
    saved = repository.save_job(
        JobRecord(
            source_url="https://example.com/jobs/backend",
            title="Backend Engineer",
            company="Example AI",
            description="Backend Engineer\nCompany: Example AI\nBuild backend services.",
            skills=["Python"],
            fit_score=45,
            priority="medium",
            status=ApplicationStatus.INTERVIEWING,
            analysis={"fit": {"score": 45}},
        )
    )
    preview = coordinator.analyze(
        JobAnalysisRequest(
            save=False,
            use_llm=False,
            use_llm_guidance=False,
            source_url=saved.source_url,
            description="Senior Backend Engineer\nCompany: Example AI\nBuild Python workflow services.",
        )
    )

    updated = coordinator.update_saved_job_analysis(saved.id, preview, source_url=saved.source_url)

    assert updated is not None
    assert updated.id == saved.id
    assert updated.status == ApplicationStatus.INTERVIEWING
    assert updated.analysis is not None
    assert updated.analysis["fit"]["score"] == preview.fit.score
    versions = repository.list_job_analysis_versions(saved.id)
    assert len(versions) == 2
    assert versions[-1]["analysis"]["fit"]["score"] == preview.fit.score


def test_metadata_refresh_does_not_create_fake_analysis_revision(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    saved = repository.save_job(
        JobRecord(
            source_url="https://example.com/jobs/backend",
            title="Backend Engineer",
            company="Example AI",
            description="Build backend services.",
            skills=["Python"],
            fit_score=80,
            priority="high",
            analysis={"fit": {"score": 80}},
        )
    )

    repository.save_job(
        JobRecord(
            source_url=saved.source_url,
            title=saved.title,
            company=saved.company,
            description=saved.description,
            skills=saved.skills,
            fit_score=saved.fit_score,
            priority=saved.priority,
            analysis=None,
        )
    )

    versions = repository.list_job_analysis_versions(saved.id)
    assert len(versions) == 1


def test_repository_migrates_legacy_analysis_and_preserves_history(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.sqlite3"
    legacy_analysis = {
        "fit": {"concerns": ["Canonical concern"]},
        "baseline_fit": {"score": 42},
        "guidance": {
            "risk_summary": ["Legacy duplicate concern"],
            "evidence": {"risk_summary": [{"claim": "Legacy duplicate concern"}]},
        },
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE jobs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source_url TEXT,
              title TEXT,
              company TEXT,
              location TEXT,
              description TEXT NOT NULL,
              skills TEXT NOT NULL,
              fit_score INTEGER NOT NULL,
              priority TEXT NOT NULL,
              status TEXT NOT NULL,
              application_type TEXT NOT NULL DEFAULT 'unknown',
              analysis_json TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO jobs (
              source_url, title, company, location, description, skills, fit_score, priority,
              status, application_type, analysis_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "https://example.com/jobs/legacy",
                "Legacy Backend Engineer",
                "Example AI",
                None,
                "Build backend services.",
                "[]",
                70,
                "medium",
                ApplicationStatus.DISCOVERED.value,
                ApplicationType.EXTERNAL_APPLICATION.value,
                json.dumps(legacy_analysis),
            ),
        )
        conn.commit()

    repository = JobRepository(db_path)
    detail = repository.get_job(1)

    assert detail is not None
    assert detail.job.analysis_schema_version == 5
    assert detail.analysis is not None
    assert "risk_summary" not in detail.analysis["guidance"]
    assert "risk_summary" not in detail.analysis["guidance"]["evidence"]
    assert detail.analysis["fit"]["growth_areas"] == []
    assert "baseline_fit" not in detail.analysis
    assert detail.analysis["extracted_posting"] is None
    versions = repository.list_job_analysis_versions(1)
    assert [version["schema_version"] for version in versions] == [1, 5]
    assert versions[0]["analysis"]["guidance"]["risk_summary"] == ["Legacy duplicate concern"]
    assert "risk_summary" not in versions[1]["analysis"]["guidance"]


def test_job_chat_persists_messages_with_fallback(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )
    analysis = coordinator.analyze(
        JobAnalysisRequest(
            use_llm=False,
            use_llm_guidance=False,
            description="""
            Senior Backend Engineer, AI Platform
            Company: Example AI
            Build Python backend services for agent workflow infrastructure.
            """,
        )
    )

    assert analysis.saved_job is not None
    response = coordinator.chat_about_job(
        analysis.saved_job.id,
        request=JobChatRequest(
            message="How should I prepare?",
            use_llm=False,
        ),
    )

    assert response is not None
    assert response.responder_used == "deterministic"
    assert "prep" in response.answer.lower() or "start" in response.answer.lower()

    messages = coordinator.repository.list_chat_messages(analysis.saved_job.id)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"


def test_global_chat_treats_my_education_background_as_profile_fact(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.local.yaml"
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(path=profile_path, audit_path=tmp_path / "profile_audit.jsonl"),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.chat_globally(
        GlobalChatRequest(
            message=(
                "my education background Example State University, Computer Engineering, 2014 - 2018 "
                "Example Tech University, Computer Science, 2018 - 2020"
            ),
            use_llm=True,
        )
    )

    profile = coordinator.profile_store.load()
    assert response.responder_used == "profile_update"
    assert "Example State University, Computer Engineering, 2014 - 2018" in profile["education"]
    assert "Example Tech University, Computer Science, 2018 - 2020" in profile["education"]


def test_job_chat_web_search_request_falls_back_when_llm_unavailable(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )
    analysis = coordinator.analyze(
        JobAnalysisRequest(
            use_llm=False,
            use_llm_guidance=False,
            description="Senior Backend Engineer\nCompany: Example AI\nBuild distributed systems.",
        )
    )

    assert analysis.saved_job is not None
    response = coordinator.chat_about_job(
        analysis.saved_job.id,
        JobChatRequest(
            message="Find recent interview questions for this company.",
            use_llm=False,
            use_web_search=True,
        ),
    )

    assert response is not None
    assert response.used_web_search is False
    assert response.citations == []
    assert "Web search was requested" in response.answer


def test_analysis_preview_chat_uses_unsaved_analysis_without_persisting(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )
    analysis = coordinator.analyze(
        JobAnalysisRequest(
            save=False,
            use_llm=False,
            use_llm_guidance=False,
            description="Senior Backend Engineer\nCompany: Example AI\nBuild distributed systems.",
        )
    )

    response = coordinator.chat_about_analysis(
        request=AnalysisChatRequest(
            analysis=analysis,
            message="Why did you list these concerns?",
            use_llm=False,
            use_web_search=False,
        )
    )

    assert response.responder_used == "deterministic"
    assert len(response.messages) == 2
    assert coordinator.repository.list_jobs() == []


def test_unified_assistant_chat_supports_analysis_preview_focus(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )
    analysis = coordinator.analyze(
        JobAnalysisRequest(
            save=False,
            use_llm=False,
            use_llm_guidance=False,
            description="Senior Backend Engineer\nCompany: Example AI\nBuild distributed systems.",
        )
    )

    response = coordinator.chat_with_focus(
        AssistantChatRequest(
            focus=AssistantFocus(type="analysis_preview", analysis=analysis),
            message="Clarify the concerns.",
            use_llm=False,
        )
    )

    assert response is not None
    assert response.focus.type == "analysis_preview"
    assert response.responder_used == "deterministic"
    assert len(response.messages) == 2
    assert coordinator.repository.list_jobs() == []


def test_prep_plan_generation_and_task_update(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    plan = generate_prep_plan(
        profile=ProfileStore().load(),
        jobs=[],
        timeline_days=3,
        hours_per_day=2,
        focus="Kubernetes, LeetCode",
    )

    saved = repository.save_prep_plan(plan)
    updated = repository.update_prep_task(saved.id, day=1, task_index=0, completed=True)

    assert saved.id is not None
    assert len(repository.list_prep_plans()) == 1
    assert updated is not None
    assert updated.days[0].tasks[0].completed is True
    assert updated.revision == 2
    assert [version["revision"] for version in repository.list_prep_plan_versions(saved.id)] == [1, 2]


def test_resume_pdf_version_is_persisted_with_provenance(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    artifact = generate_resume_artifact(
        profile=ProfileStore().load(),
        role_title="Senior Backend Engineer",
        company="Example AI",
        use_llm=False,
    )
    saved = repository.save_resume_version(
        ResumeVersion(
            role_title="Senior Backend Engineer",
            company="Example AI",
            draft=artifact.draft.model_dump(mode="json"),
            provenance=artifact.provenance,
        ),
        artifact.pdf,
    )

    assert saved.id is not None
    assert saved.provenance.generator == "deterministic"
    assert repository.get_resume_pdf(saved.id) == artifact.pdf
    assert repository.list_resume_versions()[0].role_title == "Senior Backend Engineer"


def test_profile_proposal_versions_are_append_only(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    provenance = artifact_provenance(
        generator="deterministic",
        workflow_version=PROFILE_PROPOSAL_WORKFLOW_VERSION,
        schema_version=1,
    )
    proposal = repository.create_profile_proposal(
        ProfileProposal(
            filename="resume.md",
            proposed_updates={"technical_strengths": ["Python"]},
            provenance=provenance,
        )
    )
    updated = repository.update_profile_proposal(
        proposal.id,
        proposed_updates={"technical_strengths": ["Python", "Java"]},
    )
    accepted = repository.update_profile_proposal(proposal.id, status="accepted")

    assert updated is not None
    assert accepted is not None
    assert accepted.status == "accepted"
    with sqlite3.connect(repository.path) as conn:
        rows = conn.execute(
            "SELECT revision, status FROM profile_proposal_versions WHERE proposal_id = ? ORDER BY revision",
            (proposal.id,),
        ).fetchall()
    assert rows == [(1, "pending"), (2, "pending"), (3, "accepted")]


def test_repository_bootstraps_history_for_legacy_prep_plan(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.sqlite3"
    payload = {
        "title": "Legacy plan",
        "source": "imported",
        "timeline_days": 1,
        "hours_per_day": 1,
        "days": [{"day": 1, "title": "Day 1", "tasks": []}],
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE prep_plans (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              title TEXT NOT NULL,
              source TEXT NOT NULL,
              timeline_days INTEGER NOT NULL,
              hours_per_day REAL NOT NULL,
              plan_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO prep_plans (title, source, timeline_days, hours_per_day, plan_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Legacy plan", "imported", 1, 1, json.dumps(payload), "2026-01-01", "2026-01-01"),
        )
        conn.commit()

    repository = JobRepository(db_path)
    versions = repository.list_prep_plan_versions(1)

    assert len(versions) == 1
    assert versions[0]["revision"] == 1
    assert versions[0]["plan"]["title"] == "Legacy plan"


def test_imported_prep_plan_and_resume_pdf_generation() -> None:
    plan = parse_prep_plan_text("Day 1\nStudy Kubernetes\nLeetCode arrays", title="Two day plan")
    pdf = generate_resume_pdf(
        profile=ProfileStore().load(),
        role_title="Senior Backend Engineer",
        company="Example AI",
        notes="Emphasize workflow orchestration.",
    )

    assert plan.days[0].tasks
    assert pdf.startswith(b"%PDF-")
    assert b"Senior Backend Engineer" in pdf


def test_global_chat_uses_saved_jobs_and_persists_messages(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )
    coordinator.analyze(
        JobAnalysisRequest(
            use_llm=False,
            use_llm_guidance=False,
            description="Senior Backend Engineer\nCompany: Example AI\nBuild distributed systems.",
        )
    )

    response = coordinator.chat_globally(
        GlobalChatRequest(
            message="Rank my saved jobs.",
            use_llm=False,
        )
    )

    assert response.responder_used == "deterministic"
    assert "strongest" in response.answer.lower()
    messages = coordinator.repository.list_global_chat_messages()
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"


def test_global_chat_fallback_answers_follow_up_intent_differently(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )
    coordinator.analyze(
        JobAnalysisRequest(
            use_llm=False,
            use_llm_guidance=False,
            description="""
            Senior Backend Engineer, AI Platform
            Company: Example AI
            Build Python backend services with Kubernetes and distributed workflow orchestration.
            """,
        )
    )

    gaps_response = coordinator.chat_globally(
        GlobalChatRequest(message="What gaps show up across my saved roles?", use_llm=False)
    )
    prep_response = coordinator.chat_globally(
        GlobalChatRequest(
            message="What should I prepare next?",
            session_id=gaps_response.session.id,
            use_llm=False,
        )
    )

    assert gaps_response.answer != prep_response.answer
    assert "gap" in gaps_response.answer.lower()
    assert "prep" in prep_response.answer.lower() or "sequence" in prep_response.answer.lower()


def test_job_chat_fallback_answers_follow_up_intent_differently(tmp_path: Path) -> None:
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )
    analysis = coordinator.analyze(
        JobAnalysisRequest(
            use_llm=False,
            use_llm_guidance=False,
            description="""
            Senior Backend Engineer, AI Platform
            Company: Example AI
            Build Python backend services with Kubernetes and distributed workflow orchestration.
            """,
        )
    )

    assert analysis.saved_job is not None
    gaps_response = coordinator.chat_about_job(
        analysis.saved_job.id,
        JobChatRequest(message="What gaps are saved?", use_llm=False),
    )
    resume_response = coordinator.chat_about_job(
        analysis.saved_job.id,
        JobChatRequest(message="How should I position my resume?", use_llm=False),
    )

    assert gaps_response is not None
    assert resume_response is not None
    assert gaps_response.answer != resume_response.answer
    assert "gap" in gaps_response.answer.lower()
    assert "resume" in resume_response.answer.lower()


def test_global_chat_updates_education_when_user_explicitly_requests(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.local.yaml"
    audit_path = tmp_path / "profile_audit.jsonl"
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(path=profile_path, audit_path=audit_path),
        repository=JobRepository(tmp_path / "jobs.sqlite3"),
    )

    response = coordinator.chat_globally(
        GlobalChatRequest(
            message=(
                "Please update my education background: Example State University, Computer Engineering, 2014 - 2018 "
                "Example Tech University, Computer Science, 2018 - 2020"
            ),
            use_llm=False,
        )
    )

    profile = coordinator.profile_store.load()
    assert response.responder_used == "profile_update"
    assert "Updated your local profile memory" in response.answer
    assert "Example State University, Computer Engineering, 2014 - 2018" in profile["education"]
    assert "Example Tech University, Computer Science, 2018 - 2020" in profile["education"]
    assert '"source": "assistant_chat"' in audit_path.read_text(encoding="utf-8")

    messages = coordinator.repository.list_global_chat_messages(response.session.id)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
