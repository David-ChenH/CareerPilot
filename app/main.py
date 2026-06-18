import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.artifacts import (
    PROFILE_PROPOSAL_PROMPT_VERSION,
    PROFILE_PROPOSAL_WORKFLOW_VERSION,
    artifact_provenance,
    configured_llm_model,
)
from app.agents.action_registry import ActionRegistry
from app.agents.assistant_planner import (
    ActionExecutionResult,
    ActionExecutionStatus,
    AssistantPlannedAction,
    AssistantPlannerUnavailable,
    AssistantPlan,
    AssistantPlanStatus,
    plan_assistant_actions_with_llm,
)
from app.agents.coordinator import (
    AnalysisChatRequest,
    AssistantChatRequest,
    AssistantChatResponse,
    GlobalChatRequest,
    GlobalChatResponse,
    JobAnalysisRequest,
    JobAnalysisResponse,
    JobChatRequest,
    JobChatResponse,
    JobSearchCoordinator,
)
from app.config.env import load_local_env
from app.db.models import (
    AgentTask,
    AgentTaskStatus,
    AgentTaskType,
    ApplicationStatus,
    ChatRole,
    GlobalChatMessage,
    GlobalChatSession,
    JobChatMessage,
    JobDetail,
    JobRecord,
    LeetCodeProblem,
    LeetCodeStatus,
    PrepPlan,
    ProfileProposal,
    ResumeVersion,
)
from app.tools.browser_job_fetcher import BrowserJobPageFetchError, fetch_job_page_with_browser
from app.tools.job_fetcher import JobPageFetchError, fetch_job_page
from app.tools.job_extraction import ExtractedJobPosting
from app.tools.llm_job_scorer import LLMJobScorerUnavailable
from app.tools.profile_proposal_refiner import (
    ProfileProposalRefinerUnavailable,
    ProfileProposalRefinement,
    refine_profile_proposal_deterministically,
    refine_profile_proposal_with_llm,
)
from app.tools.prep_planner import parse_prep_plan_text
from app.tools.resume_generator import generate_resume_artifact
from app.tools.llm_job_chat import DEFAULT_LLM_MODEL
from app.tools.analysis_feedback import record_analysis_feedback
from app.tools.text_budget import compact_job_text
from app.workflows.job_ingestion import JobIngestionWorkflowRunner
from app.workflows.prep_plan import PrepPlanWorkflowRequest, PrepPlanWorkflowRunner


load_local_env()

app = FastAPI(title="CareerPilot", version="0.1.0")
coordinator = JobSearchCoordinator()
action_registry = ActionRegistry()
STATIC_DIR = Path(__file__).with_name("static")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(LLMJobScorerUnavailable)
def semantic_scoring_unavailable(_request, error: LLMJobScorerUnavailable) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "Semantic job analysis is unavailable. CareerPilot does not generate a keyword-based fallback score. "
                f"{error}"
            )
        },
    )


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class CreateGlobalChatSessionRequest(BaseModel):
    title: str = "New chat"


@app.get("/chat/sessions", response_model=list[GlobalChatSession])
def list_global_chat_sessions() -> list[GlobalChatSession]:
    return coordinator.repository.list_global_chat_sessions()


@app.post("/chat/sessions", response_model=GlobalChatSession)
def create_global_chat_session(request: CreateGlobalChatSessionRequest) -> GlobalChatSession:
    return coordinator.repository.create_global_chat_session(request.title)


@app.delete("/chat/sessions/{session_id}", status_code=204)
def delete_global_chat_session(session_id: int) -> None:
    deleted = coordinator.repository.delete_global_chat_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat session not found.")


@app.get("/chat", response_model=list[GlobalChatMessage])
def list_global_chat(session_id: int | None = None) -> list[GlobalChatMessage]:
    if session_id is not None and coordinator.repository.get_global_chat_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return coordinator.repository.list_global_chat_messages(session_id)


@app.delete("/chat", status_code=204)
def clear_global_chat(session_id: int | None = None) -> None:
    if session_id is not None and coordinator.repository.get_global_chat_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    coordinator.repository.delete_global_chat_messages(session_id)


@app.post("/chat", response_model=GlobalChatResponse)
def chat_globally(request: GlobalChatRequest, background_tasks: BackgroundTasks) -> GlobalChatResponse:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Chat message cannot be empty.")
    planned_response = _maybe_run_planned_chat_actions(request, background_tasks)
    if planned_response is not None:
        return planned_response
    return coordinator.chat_globally(request)


@app.post("/assistant/chat", response_model=AssistantChatResponse)
def chat_with_assistant_context(request: AssistantChatRequest) -> AssistantChatResponse:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Chat message cannot be empty.")
    response = coordinator.chat_with_focus(request)
    if response is None:
        raise HTTPException(status_code=404, detail="Assistant focus was not found or is incomplete.")
    return response


class ProfileResponse(BaseModel):
    profile: dict[str, Any]
    source: str


class ResumeExtractRequest(BaseModel):
    filename: str | None = None
    content: str


class ResumeExtractResponse(BaseModel):
    proposal_id: int | None = None
    filename: str | None = None
    proposed_updates: dict[str, list[str]]
    summary: str


class ProfileApplyRequest(BaseModel):
    proposal_id: int | None = None
    proposed_updates: dict[str, list[str]]
    source: str = "resume_portal"


class ProfileApplyResponse(BaseModel):
    profile: dict[str, Any]
    source: str
    applied_updates: dict[str, list[str]]
    summary: str


class ProfileProposalRefineRequest(BaseModel):
    proposal_id: int | None = None
    proposed_updates: dict[str, list[str]]
    message: str
    use_llm: bool = True


class ProfileProposalRefineResponse(BaseModel):
    proposal_id: int | None = None
    answer: str
    proposed_updates: dict[str, list[str]]
    responder_used: str
    responder_warning: str | None = None


@app.get("/profile", response_model=ProfileResponse)
def get_profile() -> ProfileResponse:
    store = coordinator.profile_store
    source = "local" if store.path.exists() else "example"
    return ProfileResponse(profile=store.load(), source=source)


@app.post("/profile/resume/extract", response_model=ResumeExtractResponse)
def extract_resume_profile(request: ResumeExtractRequest) -> ResumeExtractResponse:
    if not request.content.strip():
        raise HTTPException(status_code=400, detail="Resume content cannot be empty.")
    proposed_updates = _extract_resume_updates(request.content)
    proposal = coordinator.repository.create_profile_proposal(
        ProfileProposal(
            filename=request.filename,
            proposed_updates=proposed_updates,
            provenance=artifact_provenance(
                generator="deterministic",
                workflow_version=PROFILE_PROPOSAL_WORKFLOW_VERSION,
                schema_version=1,
            ),
        )
    )
    total = sum(len(values) for values in proposed_updates.values())
    return ResumeExtractResponse(
        filename=request.filename,
        proposal_id=proposal.id,
        proposed_updates=proposed_updates,
        summary=f"Extracted {total} profile signals from the resume text. Review before saving to profile memory.",
    )


@app.post("/profile/apply", response_model=ProfileApplyResponse)
def apply_profile_updates(request: ProfileApplyRequest) -> ProfileApplyResponse:
    total = sum(len(values) for values in request.proposed_updates.values())
    if total == 0:
        raise HTTPException(status_code=400, detail="No profile updates were provided.")
    if request.proposal_id is not None:
        if coordinator.repository.get_profile_proposal(request.proposal_id) is None:
            raise HTTPException(status_code=404, detail="Profile proposal not found.")
    profile = coordinator.profile_store.apply_updates(
        request.proposed_updates,
        source=request.source,
        metadata={"proposal_id": request.proposal_id} if request.proposal_id is not None else None,
    )
    if request.proposal_id is not None:
        proposal = coordinator.repository.update_profile_proposal(request.proposal_id, status="accepted")
        if proposal is None:
            raise HTTPException(status_code=404, detail="Profile proposal not found.")
    return ProfileApplyResponse(
        profile=profile,
        source="local",
        applied_updates=request.proposed_updates,
        summary=f"Saved {total} profile facts to private local profile memory.",
    )


@app.post("/profile/proposals/refine", response_model=ProfileProposalRefineResponse)
def refine_profile_proposal(request: ProfileProposalRefineRequest) -> ProfileProposalRefineResponse:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Refinement message cannot be empty.")
    if request.proposal_id is not None and coordinator.repository.get_profile_proposal(request.proposal_id) is None:
        raise HTTPException(status_code=404, detail="Profile proposal not found.")

    responder_used = "deterministic"
    responder_warning = None
    refinement: ProfileProposalRefinement
    if request.use_llm:
        try:
            refinement = refine_profile_proposal_with_llm(
                profile=coordinator.profile_store.load(),
                proposed_updates=request.proposed_updates,
                message=request.message,
            )
            responder_used = "llm"
        except ProfileProposalRefinerUnavailable as error:
            responder_warning = str(error)
            refinement = refine_profile_proposal_deterministically(request.proposed_updates, request.message)
    else:
        refinement = refine_profile_proposal_deterministically(request.proposed_updates, request.message)

    if request.proposal_id is not None:
        coordinator.repository.update_profile_proposal(
            request.proposal_id,
            proposed_updates=refinement.proposed_updates,
            provenance=artifact_provenance(
                generator=responder_used,
                workflow_version=PROFILE_PROPOSAL_WORKFLOW_VERSION,
                schema_version=1,
                prompt_version=PROFILE_PROPOSAL_PROMPT_VERSION if responder_used == "llm" else None,
                model=configured_llm_model(DEFAULT_LLM_MODEL) if responder_used == "llm" else None,
            ),
        )

    return ProfileProposalRefineResponse(
        proposal_id=request.proposal_id,
        answer=refinement.answer,
        proposed_updates=refinement.proposed_updates,
        responder_used=responder_used,
        responder_warning=responder_warning,
    )


@app.post("/jobs/analyze", response_model=JobAnalysisResponse)
def analyze_job(request: JobAnalysisRequest) -> JobAnalysisResponse:
    if not request.description.strip():
        raise HTTPException(status_code=400, detail="Job description cannot be empty.")
    return coordinator.analyze(request)


class FetchJobRequest(BaseModel):
    url: str
    save: bool = True
    use_browser_fallback: bool = True
    use_llm: bool = True
    use_llm_guidance: bool = True


class BackgroundJobIngestRequest(BaseModel):
    url: str
    save: bool = True
    use_browser_fallback: bool = True
    use_llm: bool = True
    use_llm_guidance: bool = True


class SaveAnalyzedJobRequest(BaseModel):
    analysis: JobAnalysisResponse
    source_url: str | None = None


class UpdateJobAnalysisRequest(BaseModel):
    analysis: JobAnalysisResponse
    source_url: str | None = None
    reason: str | None = None


class AnalysisFeedbackRequest(BaseModel):
    analysis: JobAnalysisResponse
    feedback_type: str
    note: str | None = None
    source_url: str | None = None


class AnalysisFeedbackResponse(BaseModel):
    id: str
    created_at: str
    feedback_type: str
    summary: str


class PrepPlanGenerateRequest(BaseModel):
    timeline_days: int = 14
    hours_per_day: float = 2
    focus: str | None = None
    job_id: int | None = None
    use_llm: bool = True


class PrepPlanImportRequest(BaseModel):
    title: str = "Imported prep plan"
    content: str


class PrepTaskUpdateRequest(BaseModel):
    completed: bool


class LeetCodeProblemRequest(BaseModel):
    title: str
    url: str
    category: str
    tags: list[str] = Field(default_factory=list)
    note: str | None = None
    status: LeetCodeStatus = LeetCodeStatus.TODO


class ResumeGenerateRequest(BaseModel):
    role_title: str
    company: str | None = None
    job_id: int | None = None
    notes: str | None = None
    use_llm: bool = True


@app.post("/jobs/fetch-and-analyze", response_model=JobAnalysisResponse)
def fetch_and_analyze_job(request: FetchJobRequest) -> JobAnalysisResponse:
    return _fetch_and_analyze_job(
        url=request.url,
        save=request.save,
        use_browser_fallback=request.use_browser_fallback,
        use_llm=request.use_llm,
        use_llm_guidance=request.use_llm_guidance,
    )


@app.post("/jobs/background-fetch-and-save", response_model=AgentTask)
def start_background_job_ingest(
    request: BackgroundJobIngestRequest,
    background_tasks: BackgroundTasks,
) -> AgentTask:
    if not request.url.strip():
        raise HTTPException(status_code=400, detail="Job URL cannot be empty.")
    task = _start_job_ingest_task(request)
    background_tasks.add_task(_run_background_job_ingest, task.id, request)
    return task


@app.get("/jobs/background-tasks/{task_id}", response_model=AgentTask)
def get_background_job_ingest(task_id: str) -> AgentTask:
    task = coordinator.repository.get_agent_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Background job task not found.")
    return task


@app.post("/jobs/save-analysis", response_model=JobRecord)
def save_analyzed_job(request: SaveAnalyzedJobRequest) -> JobRecord:
    return coordinator.save_analysis(request.analysis, source_url=request.source_url)


@app.patch("/jobs/{job_id}/analysis", response_model=JobRecord)
def update_saved_job_analysis(job_id: int, request: UpdateJobAnalysisRequest) -> JobRecord:
    updated = coordinator.update_saved_job_analysis(
        job_id=job_id,
        analysis=request.analysis,
        source_url=request.source_url,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return updated


@app.post("/jobs/analysis/feedback", response_model=AnalysisFeedbackResponse)
def save_analysis_feedback(request: AnalysisFeedbackRequest) -> AnalysisFeedbackResponse:
    allowed_feedback = {"accurate", "missing_gap", "wrong_concern", "too_generic", "other"}
    if request.feedback_type not in allowed_feedback:
        raise HTTPException(status_code=400, detail=f"feedback_type must be one of: {', '.join(sorted(allowed_feedback))}.")
    record = record_analysis_feedback(
        feedback_type=request.feedback_type,
        note=request.note,
        analysis=request.analysis.model_dump(exclude={"saved_job"}),
        source_url=request.source_url,
    )
    return AnalysisFeedbackResponse(
        id=record["id"],
        created_at=record["created_at"],
        feedback_type=record["feedback_type"],
        summary="Saved analysis feedback locally for future evaluation and prompt improvement.",
    )


@app.get("/prep-plans", response_model=list[PrepPlan])
def list_prep_plans() -> list[PrepPlan]:
    return coordinator.repository.list_prep_plans()


@app.get("/prep-plans/{plan_id}/versions")
def list_prep_plan_versions(plan_id: int) -> list[dict]:
    if coordinator.repository.get_prep_plan(plan_id) is None:
        raise HTTPException(status_code=404, detail="Prep plan not found.")
    return coordinator.repository.list_prep_plan_versions(plan_id)


@app.post("/prep-plans/generate", response_model=PrepPlan)
def generate_preparation_plan(request: PrepPlanGenerateRequest) -> PrepPlan:
    profile = coordinator.profile_store.load_model()
    jobs = coordinator.repository.list_jobs()
    coding_problems = coordinator.repository.list_leetcode_problems()
    plan = PrepPlanWorkflowRunner(
        profile=profile,
        jobs=jobs,
        coding_problems=coding_problems,
    ).run(
        PrepPlanWorkflowRequest(
            timeline_days=request.timeline_days,
            hours_per_day=request.hours_per_day,
            focus=request.focus,
            job_id=request.job_id,
            use_llm=request.use_llm,
        )
    )
    return coordinator.repository.save_prep_plan(plan)


@app.post("/prep-plans/import", response_model=PrepPlan)
def import_preparation_plan(request: PrepPlanImportRequest) -> PrepPlan:
    if not request.content.strip():
        raise HTTPException(status_code=400, detail="Prep plan text cannot be empty.")
    return coordinator.repository.save_prep_plan(parse_prep_plan_text(request.content, title=request.title))


@app.patch("/prep-plans/{plan_id}/days/{day}/tasks/{task_index}", response_model=PrepPlan)
def update_preparation_task(plan_id: int, day: int, task_index: int, request: PrepTaskUpdateRequest) -> PrepPlan:
    plan = coordinator.repository.update_prep_task(plan_id, day, task_index, request.completed)
    if plan is None:
        raise HTTPException(status_code=404, detail="Prep plan task not found.")
    return plan


@app.get("/leetcode/problems", response_model=list[LeetCodeProblem])
def list_leetcode_problems() -> list[LeetCodeProblem]:
    return coordinator.repository.list_leetcode_problems()


@app.post("/leetcode/problems", response_model=LeetCodeProblem)
def create_leetcode_problem(request: LeetCodeProblemRequest) -> LeetCodeProblem:
    return coordinator.repository.create_leetcode_problem(_leetcode_problem_from_request(request))


@app.put("/leetcode/problems/{problem_id}", response_model=LeetCodeProblem)
def update_leetcode_problem(problem_id: int, request: LeetCodeProblemRequest) -> LeetCodeProblem:
    updated = coordinator.repository.update_leetcode_problem(problem_id, _leetcode_problem_from_request(request))
    if updated is None:
        raise HTTPException(status_code=404, detail="LeetCode problem not found.")
    return updated


@app.delete("/leetcode/problems/{problem_id}", status_code=204)
def delete_leetcode_problem(problem_id: int) -> None:
    deleted = coordinator.repository.delete_leetcode_problem(problem_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="LeetCode problem not found.")


@app.post("/resumes/generate")
def generate_resume(request: ResumeGenerateRequest) -> Response:
    if not request.role_title.strip():
        raise HTTPException(status_code=400, detail="Role title is required.")
    detail = coordinator.repository.get_job(request.job_id) if request.job_id else None
    if request.job_id and detail is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    job = detail.job if detail else None
    artifact = generate_resume_artifact(
        profile=coordinator.profile_store.load_model(),
        role_title=request.role_title,
        company=request.company,
        job=job,
        notes=request.notes,
        use_llm=request.use_llm,
    )
    resume = coordinator.repository.save_resume_version(
        ResumeVersion(
            role_title=request.role_title,
            company=request.company,
            job_id=request.job_id,
            notes=request.notes,
            draft=artifact.draft.model_dump(mode="json"),
            provenance=artifact.provenance,
        ),
        artifact.pdf,
    )
    filename = f"careerpilot-resume-{request.role_title.lower().replace(' ', '-')}.pdf"
    return Response(
        content=artifact.pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-CareerPilot-Resume-Version": str(resume.id),
        },
    )


@app.get("/resumes", response_model=list[ResumeVersion])
def list_resume_versions() -> list[ResumeVersion]:
    return coordinator.repository.list_resume_versions()


@app.get("/resumes/{resume_id}/pdf")
def download_resume_version(resume_id: int) -> Response:
    pdf = coordinator.repository.get_resume_pdf(resume_id)
    if pdf is None:
        raise HTTPException(status_code=404, detail="Resume version not found.")
    return Response(content=pdf, media_type="application/pdf")


def _leetcode_problem_from_request(request: LeetCodeProblemRequest) -> LeetCodeProblem:
    title = request.title.strip()
    url = request.url.strip()
    category = request.category.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Problem title cannot be empty.")
    if not url:
        raise HTTPException(status_code=400, detail="Problem link cannot be empty.")
    if not category:
        raise HTTPException(status_code=400, detail="Problem category cannot be empty.")
    tags = [tag.strip() for tag in request.tags if tag.strip()]
    return LeetCodeProblem(
        title=title,
        url=url,
        category=category,
        tags=list(dict.fromkeys(tags)),
        note=request.note.strip() if request.note and request.note.strip() else None,
        status=request.status,
    )


@app.post("/jobs/analysis/chat", response_model=JobChatResponse)
def chat_about_analysis_preview(request: AnalysisChatRequest) -> JobChatResponse:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Chat message cannot be empty.")
    return coordinator.chat_about_analysis(request)


@app.get("/jobs", response_model=list[JobRecord])
def list_jobs() -> list[JobRecord]:
    return coordinator.repository.list_jobs()


@app.get("/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: int) -> JobDetail:
    detail = coordinator.repository.get_job(job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return detail


@app.post("/jobs/{job_id}/regenerate-analysis", response_model=AgentTask)
def regenerate_job_analysis(job_id: int, background_tasks: BackgroundTasks) -> AgentTask:
    detail = coordinator.repository.get_job(job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if not detail.job.source_url:
        raise HTTPException(
            status_code=400,
            detail="This saved job does not have a source link. Paste its current description into Analyze Job to refresh it.",
        )
    request = BackgroundJobIngestRequest(
        url=detail.job.source_url,
        save=True,
        use_browser_fallback=True,
        use_llm=True,
        use_llm_guidance=True,
    )
    task = _start_job_ingest_task(request)
    background_tasks.add_task(_run_background_job_ingest, task.id, request)
    return task


@app.get("/jobs/{job_id}/analysis-versions")
def list_job_analysis_versions(job_id: int) -> list[dict]:
    if coordinator.repository.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return coordinator.repository.list_job_analysis_versions(job_id)


@app.get("/profile/proposals/{proposal_id}", response_model=ProfileProposal)
def get_profile_proposal(proposal_id: int) -> ProfileProposal:
    proposal = coordinator.repository.get_profile_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Profile proposal not found.")
    return proposal


@app.get("/profile/proposals/{proposal_id}/versions")
def list_profile_proposal_versions(proposal_id: int) -> list[dict]:
    if coordinator.repository.get_profile_proposal(proposal_id) is None:
        raise HTTPException(status_code=404, detail="Profile proposal not found.")
    return coordinator.repository.list_profile_proposal_versions(proposal_id)


@app.get("/jobs/{job_id}/chat", response_model=list[JobChatMessage])
def list_job_chat(job_id: int) -> list[JobChatMessage]:
    detail = coordinator.repository.get_job(job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return coordinator.repository.list_chat_messages(job_id)


@app.delete("/jobs/{job_id}/chat", status_code=204)
def clear_job_chat(job_id: int) -> None:
    detail = coordinator.repository.get_job(job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    coordinator.repository.delete_chat_messages(job_id)


@app.post("/jobs/{job_id}/chat", response_model=JobChatResponse)
def chat_about_job(job_id: int, request: JobChatRequest) -> JobChatResponse:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Chat message cannot be empty.")
    response = coordinator.chat_about_job(job_id, request)
    if response is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return response


@app.post("/jobs/{job_id}/chat/stream")
def stream_chat_about_job(job_id: int, request: JobChatRequest) -> StreamingResponse:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Chat message cannot be empty.")
    if coordinator.repository.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    def event_stream():
        try:
            yield _stream_event("status", message="Loading saved job context")
            yield _stream_event("status", message="Reading profile and analysis memory")
            if request.use_web_search:
                yield _stream_event("status", message="Preparing web search")
            yield _stream_event("status", message="Generating answer")
            response = coordinator.chat_about_job(job_id, request)
            if response is None:
                yield _stream_event("error", message="Job not found.")
                return
            for chunk in _chunk_text(response.answer):
                yield _stream_event("chunk", text=chunk)
                time.sleep(0.015)
            yield _stream_event(
                "done",
                message=response.messages[-1].model_dump() if response.messages else None,
                responder_used=response.responder_used,
                responder_warning=response.responder_warning,
                used_web_search=response.used_web_search,
                citations=response.citations,
            )
        except Exception as error:
            yield _stream_event("error", message=str(error) or "Chat request failed.")

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.patch("/jobs/{job_id}/status", response_model=JobRecord)
def update_job_status(job_id: int, status: ApplicationStatus) -> JobRecord:
    updated = coordinator.repository.update_status(job_id, status)
    if updated is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return updated


@app.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: int) -> None:
    deleted = coordinator.repository.delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Job not found.")


def _stream_event(event_type: str, **payload) -> str:
    return json.dumps({"type": event_type, **payload}, default=str) + "\n"


def _maybe_run_planned_chat_actions(
    request: GlobalChatRequest,
    background_tasks: BackgroundTasks,
) -> GlobalChatResponse | None:
    if not request.use_llm:
        return None

    existing_session = _existing_chat_session(request)
    messages = [
        *(coordinator.repository.list_global_chat_messages(existing_session.id) if existing_session and existing_session.id else []),
        GlobalChatMessage(
            session_id=existing_session.id if existing_session else None,
            role=ChatRole.USER,
            content=request.message.strip(),
        ),
    ]
    try:
        plan = plan_assistant_actions_with_llm(
            profile=coordinator.profile_store.load(),
            jobs=coordinator.repository.list_jobs(),
            messages=messages,
            active_context={"type": "global_chat", "session_id": existing_session.id if existing_session else None},
        )
    except AssistantPlannerUnavailable:
        return None

    if plan.status == AssistantPlanStatus.ANSWER_ONLY and not plan.actions:
        return None

    if plan.status == AssistantPlanStatus.NEEDS_CLARIFICATION:
        return _record_planned_chat_response(
            request=request,
            session=_resolve_chat_session(request),
            answer=plan.clarification_question or "Can you clarify what you want CareerPilot to do?",
            responder_used="planner:clarification",
            assistant_plan=plan,
        )

    if plan.status == AssistantPlanStatus.REJECTED:
        return _record_planned_chat_response(
            request=request,
            session=_resolve_chat_session(request),
            answer=plan.clarification_question or "I cannot safely perform that action from chat.",
            responder_used="planner:rejected",
            assistant_plan=plan,
        )

    if not plan.actions:
        return None

    validation_results = [
        result
        for result in (action_registry.validate_planned_action(action) for action in plan.actions)
        if result is not None
    ]
    if validation_results:
        return _record_planned_chat_response(
            request=request,
            session=_resolve_chat_session(request),
            answer=_planned_action_response(plan, validation_results),
            responder_used="planner:validation",
            assistant_plan=plan,
            action_results=validation_results,
        )

    tasks: list[AgentTask] = []
    execution_results: list[ActionExecutionResult] = []
    for action in plan.actions:
        result, task = _execute_planned_action(action, request, background_tasks)
        execution_results.append(result)
        if task is not None:
            tasks.append(task)

    return _record_planned_chat_response(
        request=request,
        session=_resolve_chat_session(request),
        answer=_planned_action_response(plan, execution_results),
        responder_used="planner:executed",
        assistant_plan=plan,
        action_results=execution_results,
        actions=tasks,
    )


def _resolve_chat_session(request: GlobalChatRequest) -> GlobalChatSession:
    session = (
        coordinator.repository.get_global_chat_session(request.session_id)
        if request.session_id is not None
        else coordinator.repository.create_global_chat_session(_chat_title_from_message(request.message))
    )
    if session is None:
        session = coordinator.repository.create_global_chat_session(_chat_title_from_message(request.message))
    return session


def _existing_chat_session(request: GlobalChatRequest) -> GlobalChatSession | None:
    if request.session_id is None:
        return None
    return coordinator.repository.get_global_chat_session(request.session_id)


def _record_planned_chat_response(
    *,
    request: GlobalChatRequest,
    session: GlobalChatSession,
    answer: str,
    responder_used: str,
    assistant_plan: AssistantPlan,
    action_results: list[ActionExecutionResult] | None = None,
    actions: list[AgentTask] | None = None,
) -> GlobalChatResponse:
    user_message = coordinator.repository.add_global_chat_message(
        GlobalChatMessage(
            session_id=session.id,
            role=ChatRole.USER,
            content=request.message.strip(),
        )
    )
    assistant_message = coordinator.repository.add_global_chat_message(
        GlobalChatMessage(
            session_id=session.id,
            role=ChatRole.ASSISTANT,
            content=answer,
        )
    )
    return GlobalChatResponse(
        answer=answer,
        session=coordinator.repository.get_global_chat_session(session.id) or session,
        messages=[user_message, assistant_message],
        responder_used=responder_used,
        used_web_search=False,
        citations=[],
        actions=actions or [],
        assistant_plan=assistant_plan,
        action_results=action_results or [],
    )


def _execute_planned_action(
    action: AssistantPlannedAction,
    request: GlobalChatRequest,
    background_tasks: BackgroundTasks,
) -> tuple[ActionExecutionResult, AgentTask | None]:
    if action.name == "ingest_job_from_url":
        url = str(action.arguments.url or "").strip()
        save = bool(action.arguments.save)
        if not url:
            return (
                ActionExecutionResult(
                    action_name=action.name,
                    status=ActionExecutionStatus.REJECTED,
                    summary="Rejected job ingestion: missing URL.",
                ),
                None,
            )

        task_request = BackgroundJobIngestRequest(
            url=url,
            save=save,
            use_browser_fallback=True,
            use_llm=request.use_llm,
            use_llm_guidance=True,
        )
        task = _start_job_ingest_task(task_request)
        background_tasks.add_task(_run_background_job_ingest, task.id, task_request)
        return (
            ActionExecutionResult(
                action_name=action.name,
                status=ActionExecutionStatus.EXECUTED,
                summary=(
                    "Started job ingestion and analysis."
                    if save
                    else "Started job ingestion and analysis preview."
                ),
                details={"task_id": task.id, "url": url, "save": save},
            ),
            task,
        )

    if action.name == "update_profile_memory":
        normalized_updates = action.arguments.proposed_updates.to_updates()
        if not any(normalized_updates.values()):
            return (
                ActionExecutionResult(
                    action_name=action.name,
                    status=ActionExecutionStatus.REJECTED,
                    summary="Rejected profile update: no profile facts were provided.",
                ),
                None,
            )
        coordinator.profile_store.apply_updates(
            normalized_updates,
            source="assistant_planner",
            metadata={"chat_session_id": request.session_id},
        )
        return (
            ActionExecutionResult(
                action_name=action.name,
                status=ActionExecutionStatus.EXECUTED,
                summary="Updated local profile memory.",
                details={"updated_fields": sorted(normalized_updates)},
            ),
            None,
        )

    if action.name == "generate_prep_plan":
        job_id = action.arguments.job_id
        if job_id is not None and coordinator.repository.get_job(job_id) is None:
            return (
                ActionExecutionResult(
                    action_name=action.name,
                    status=ActionExecutionStatus.REJECTED,
                    summary=f"Rejected prep-plan generation: saved job `{job_id}` was not found.",
                ),
                None,
            )

        timeline_days = action.arguments.timeline_days or 14
        hours_per_day = action.arguments.hours_per_day or 2
        plan = PrepPlanWorkflowRunner(
            profile=coordinator.profile_store.load_model(),
            jobs=coordinator.repository.list_jobs(),
            coding_problems=coordinator.repository.list_leetcode_problems(),
        ).run(
            PrepPlanWorkflowRequest(
                timeline_days=timeline_days,
                hours_per_day=max(hours_per_day, 0.5),
                focus=action.arguments.focus,
                job_id=job_id,
                use_llm=request.use_llm,
            )
        )
        saved = coordinator.repository.save_prep_plan(plan)
        return (
            ActionExecutionResult(
                action_name=action.name,
                status=ActionExecutionStatus.EXECUTED,
                summary=f"Generated prep plan `{saved.title}`.",
                details={
                    "prep_plan_id": saved.id,
                    "title": saved.title,
                    "timeline_days": saved.timeline_days,
                    "hours_per_day": saved.hours_per_day,
                    "job_id": job_id,
                },
            ),
            None,
        )

    if action.name == "generate_resume":
        job_id = action.arguments.job_id
        detail = coordinator.repository.get_job(job_id) if job_id is not None else None
        if job_id is not None and detail is None:
            return (
                ActionExecutionResult(
                    action_name=action.name,
                    status=ActionExecutionStatus.REJECTED,
                    summary=f"Rejected resume generation: saved job `{job_id}` was not found.",
                ),
                None,
            )

        job = detail.job if detail else None
        role_title = (action.arguments.role_title or (job.title if job else "") or "").strip()
        if not role_title:
            return (
                ActionExecutionResult(
                    action_name=action.name,
                    status=ActionExecutionStatus.REJECTED,
                    summary="Rejected resume generation: no target role was provided.",
                ),
                None,
            )
        company = (action.arguments.company or (job.company if job else None) or "").strip() or None
        artifact = generate_resume_artifact(
            profile=coordinator.profile_store.load_model(),
            role_title=role_title,
            company=company,
            job=job,
            notes=action.arguments.notes,
            use_llm=request.use_llm,
        )
        resume = coordinator.repository.save_resume_version(
            ResumeVersion(
                role_title=role_title,
                company=company,
                job_id=job_id,
                notes=action.arguments.notes,
                draft=artifact.draft.model_dump(mode="json"),
                provenance=artifact.provenance,
            ),
            artifact.pdf,
        )
        return (
            ActionExecutionResult(
                action_name=action.name,
                status=ActionExecutionStatus.EXECUTED,
                summary=f"Generated resume version for `{role_title}`.",
                details={
                    "resume_id": resume.id,
                    "role_title": role_title,
                    "company": company,
                    "job_id": job_id,
                },
            ),
            None,
        )

    if action.name == "compare_saved_jobs":
        return (_compare_saved_jobs(action.arguments.job_ids), None)

    return (
        ActionExecutionResult(
            action_name=action.name,
            status=ActionExecutionStatus.REJECTED,
            summary=f"Unsupported assistant action: {action.name}.",
        ),
        None,
    )


def _planned_action_response(plan: AssistantPlan, results: list[ActionExecutionResult]) -> str:
    if any(result.status == ActionExecutionStatus.NEEDS_CONFIRMATION for result in results):
        lines = ["I can do that, but I need your confirmation before changing local data."]
        for result in results:
            lines.append(f"- {result.summary}")
            arguments = result.details.get("arguments")
            if arguments:
                lines.append(f"  Proposed details: `{json.dumps(arguments, ensure_ascii=True)}`")
        lines.append("Reply with a clear confirmation if you want me to proceed.")
        return "\n".join(lines)

    if any(result.status == ActionExecutionStatus.REJECTED for result in results):
        lines = ["I could not safely run the requested action."]
        lines.extend(f"- {result.summary}" for result in results)
        return "\n".join(lines)

    if any(result.status == ActionExecutionStatus.FAILED for result in results):
        lines = ["I tried to run the planned action, but something failed."]
        lines.extend(f"- {result.summary}" for result in results)
        return "\n".join(lines)

    executed = [result for result in results if result.status == ActionExecutionStatus.EXECUTED]
    if executed:
        lines = [plan.intent_summary.strip() or "I started the requested action."]
        for result in executed:
            detail = result.details
            if result.action_name == "ingest_job_from_url" and detail.get("task_id"):
                outcome = "analyze it and save it to the tracker" if detail.get("save") else "fetch and analyze it"
                lines.append(
                    f"- Started a background workflow to {outcome}: task `{detail['task_id']}`."
                )
            else:
                lines.append(f"- {result.summary}")
        return "\n".join(lines)

    return plan.clarification_question or plan.intent_summary or "I reviewed the request."


def _compare_saved_jobs(job_ids: list[int]) -> ActionExecutionResult:
    saved_jobs = coordinator.repository.list_jobs()
    if job_ids:
        requested = set(job_ids)
        jobs = [job for job in saved_jobs if job.id in requested]
        missing = sorted(requested - {job.id for job in jobs if job.id is not None})
        if missing:
            return ActionExecutionResult(
                action_name="compare_saved_jobs",
                status=ActionExecutionStatus.REJECTED,
                summary=f"Could not compare saved jobs because these job ids were not found: {missing}.",
            )
    else:
        jobs = [
            job
            for job in saved_jobs
            if job.status
            in {
                ApplicationStatus.DISCOVERED,
                ApplicationStatus.INTERESTED,
                ApplicationStatus.APPLIED,
                ApplicationStatus.INTERVIEWING,
                ApplicationStatus.OFFER,
            }
        ]

    if not jobs:
        return ActionExecutionResult(
            action_name="compare_saved_jobs",
            status=ActionExecutionStatus.REJECTED,
            summary="No saved jobs are available to compare yet.",
        )

    ranked = sorted(jobs, key=_job_comparison_rank, reverse=True)
    top_lines = [
        (
            f"{index}. {job.title or 'Untitled role'} at {job.company or 'Unknown company'} "
            f"({job.priority}, score {job.fit_score}, {job.application_type.value})"
        )
        for index, job in enumerate(ranked[:5], start=1)
    ]
    return ActionExecutionResult(
        action_name="compare_saved_jobs",
        status=ActionExecutionStatus.EXECUTED,
        summary="Compared saved jobs by priority, fit score, application status, and application type.\n"
        + "\n".join(top_lines),
        details={
            "ranked_jobs": [
                {
                    "id": job.id,
                    "title": job.title,
                    "company": job.company,
                    "priority": job.priority,
                    "fit_score": job.fit_score,
                    "status": job.status.value,
                    "application_type": job.application_type.value,
                }
                for job in ranked
            ]
        },
    )


def _job_comparison_rank(job: JobRecord) -> tuple[int, int, int, int]:
    priority_rank = {"high": 3, "medium": 2, "low": 1}.get(job.priority, 0)
    status_rank = {
        ApplicationStatus.INTERVIEWING: 5,
        ApplicationStatus.OFFER: 4,
        ApplicationStatus.APPLIED: 3,
        ApplicationStatus.INTERESTED: 2,
        ApplicationStatus.DISCOVERED: 1,
        ApplicationStatus.REJECTED: 0,
    }.get(job.status, 0)
    application_type_rank = 1 if job.application_type.value == "internal_transfer" else 0
    return (priority_rank, job.fit_score, status_rank, application_type_rank)


def _start_job_ingest_task(request: BackgroundJobIngestRequest) -> AgentTask:
    return coordinator.repository.create_agent_task(
        task_type=AgentTaskType.JOB_LINK_INGEST,
        task_input={
            "url": request.url,
            "save": request.save,
            "use_browser_fallback": request.use_browser_fallback,
            "use_llm": request.use_llm,
            "use_llm_guidance": request.use_llm_guidance,
        },
        task_id=str(uuid4()),
    )


def _chat_title_from_message(message: str) -> str:
    words = message.strip().split()
    if not words:
        return "New chat"
    return " ".join(words[:8])[:80]


def _fetch_and_analyze_job(
    url: str,
    save: bool,
    use_browser_fallback: bool,
    use_llm: bool,
    use_llm_guidance: bool,
) -> JobAnalysisResponse:
    fetched_page, compacted_text = _fetch_job_description(url, use_browser_fallback)

    return coordinator.analyze(
        JobAnalysisRequest(
            description=compacted_text.text,
            extracted_posting=fetched_page.extracted_posting,
            save=save,
            source_url=fetched_page.url,
            page_title=fetched_page.title,
            use_llm=use_llm,
            use_llm_guidance=use_llm_guidance,
        )
    )


def _fetch_job_description(url: str, use_browser_fallback: bool):
    http_error: JobPageFetchError | None = None
    try:
        fetched_page = fetch_job_page(url)
    except JobPageFetchError as error:
        http_error = error
        if not use_browser_fallback:
            raise HTTPException(status_code=400, detail=str(error)) from error
        try:
            fetched_page = fetch_job_page_with_browser(url)
        except BrowserJobPageFetchError as browser_error:
            detail = (
                "Could not fetch readable job text. "
                f"Plain HTTP fetch: {http_error}. "
                f"Browser fetch: {browser_error}"
            )
            raise HTTPException(status_code=400, detail=detail) from browser_error
    else:
        if use_browser_fallback:
            try:
                rendered_page = fetch_job_page_with_browser(url)
                rendered_page.extracted_posting = _merge_extracted_postings(
                    metadata_posting=fetched_page.extracted_posting,
                    content_posting=rendered_page.extracted_posting,
                )
                fetched_page = rendered_page
            except BrowserJobPageFetchError:
                # Canonical structured data is still usable when rendered enrichment is unavailable.
                pass

    description = (
        fetched_page.extracted_posting.analysis_text(fetched_page.text)
        if fetched_page.extracted_posting
        else fetched_page.text
    )
    if fetched_page.title:
        description = f"{fetched_page.title}\n\n{description}"
    return fetched_page, compact_job_text(description)


def _merge_extracted_postings(
    metadata_posting: ExtractedJobPosting | None,
    content_posting: ExtractedJobPosting | None,
) -> ExtractedJobPosting | None:
    if content_posting is None:
        return metadata_posting
    if metadata_posting is None:
        return content_posting
    return content_posting.model_copy(
        update={
            "metadata": {**content_posting.metadata, **metadata_posting.metadata},
            "warnings": [*metadata_posting.warnings, *content_posting.warnings],
        }
    )


def _fetch_summary(url: str, compacted_text, extraction_source: str) -> str:
    source_summary = extraction_source.replace("_", " ")
    if compacted_text.was_compacted:
        return (
            f"Fetched {compacted_text.original_length} characters from {url} using {source_summary}; "
            f"compacted to {compacted_text.compacted_length} characters before analysis."
        )
    return f"Fetched {compacted_text.compacted_length} characters from {url} using {source_summary}."


def _run_background_job_ingest(task_id: str, request: BackgroundJobIngestRequest) -> None:
    try:
        JobIngestionWorkflowRunner(
            coordinator=coordinator,
            fetch_job_description=_fetch_job_description,
            fetch_summary=_fetch_summary,
        ).run(task_id, request)
    except Exception as error:
        message = str(error) or "Background job ingest failed."
        task = coordinator.repository.get_agent_task(task_id)
        if task and task.steps:
            running_step = next((step for step in reversed(task.steps) if step.status == "running"), None)
            if running_step:
                coordinator.repository.fail_agent_task_step(task_id, running_step.name, message)
        coordinator.repository.update_agent_task(task_id, status=AgentTaskStatus.FAILED, error=message)


def _chunk_text(text: str, words_per_chunk: int = 5):
    words = text.split()
    if not words:
        return
    for index in range(0, len(words), words_per_chunk):
        suffix = " " if index + words_per_chunk < len(words) else ""
        yield " ".join(words[index : index + words_per_chunk]) + suffix


def _extract_resume_updates(content: str) -> dict[str, list[str]]:
    lines = [line.strip(" -*\t") for line in content.splitlines()]
    useful_lines = [line for line in lines if len(line) >= 3]
    lower_content = content.lower()

    skills = []
    for skill in [
        "Python",
        "Java",
        "AWS",
        "Lambda",
        "Step Functions",
        "Kubernetes",
        "EKS",
        "Docker",
        "FastAPI",
        "Distributed systems",
        "Backend APIs",
        "Workflow orchestration",
        "LLM",
        "Agentic systems",
    ]:
        if skill.lower() in lower_content:
            skills.append(skill)

    experience = [
        line
        for line in useful_lines
        if any(keyword in line.lower() for keyword in ["built", "designed", "developed", "led", "maintained", "implemented"])
    ][:8]

    preferences = [
        line
        for line in useful_lines
        if any(keyword in line.lower() for keyword in ["target", "interested", "seeking", "looking for", "preferred"])
    ][:5]

    return {
        "technical_strengths": _dedupe(skills),
        "experience_highlights": _dedupe(experience),
        "preferences": _dedupe(preferences),
    }


def _dedupe(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result
