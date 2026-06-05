from pydantic import BaseModel, Field

from app.artifacts import (
    JOB_ANALYSIS_PROMPT_VERSION,
    JOB_ANALYSIS_WORKFLOW_VERSION,
    artifact_provenance,
    configured_llm_model,
)
from app.db.models import AgentTask, ApplicationStatus, ApplicationType, ChatRole, GlobalChatMessage, GlobalChatSession, JobChatMessage, JobDetail, JobRecord
from app.db.repository import JobRepository
from app.memory.profile_store import ProfileStore
from app.tools.job_parser import ParsedJob, parse_job_description
from app.tools.job_extraction import ExtractedJobPosting
from app.tools.llm_global_chat import LLMGlobalChatUnavailable, answer_global_chat_with_llm
from app.tools.llm_job_chat import LLMJobChatUnavailable, answer_job_chat_with_llm
from app.tools.llm_job_guidance import (
    JobApplicationGuidance,
    LLMJobGuidanceUnavailable,
    generate_job_guidance_with_llm,
)
from app.tools.llm_job_parser import LLMJobParserUnavailable, parse_job_with_llm, parse_large_job_with_llm
from app.tools.llm_job_scorer import score_job_fit_with_llm
from app.tools.profile_update_intent import extract_profile_updates_from_message
from app.tools.scoring import JobFit
from app.tools.text_budget import compact_job_text
from app.tools.llm_job_chat import DEFAULT_LLM_MODEL


class JobAnalysisRequest(BaseModel):
    description: str
    extracted_posting: ExtractedJobPosting | None = None
    save: bool = True
    source_url: str | None = None
    page_title: str | None = None
    use_llm: bool = True
    use_llm_guidance: bool = True


class JobAnalysisResponse(BaseModel):
    extracted_posting: ExtractedJobPosting | None = None
    parsed_job: ParsedJob
    fit: JobFit
    parser_used: str
    parser_warning: str | None = None
    scorer_used: str
    guidance: JobApplicationGuidance
    guidance_used: str
    guidance_warning: str | None = None
    saved_job: JobRecord | None = None
    resume_emphasis: list[str] = Field(default_factory=list)
    prep_topics: list[str] = Field(default_factory=list)


class JobChatRequest(BaseModel):
    message: str
    use_llm: bool = True
    use_web_search: bool = False


class JobChatResponse(BaseModel):
    answer: str
    messages: list[JobChatMessage]
    responder_used: str
    responder_warning: str | None = None
    used_web_search: bool = False
    citations: list[dict[str, str]] = Field(default_factory=list)


class AnalysisChatRequest(BaseModel):
    analysis: JobAnalysisResponse
    message: str
    history: list[JobChatMessage] = Field(default_factory=list)
    source_url: str | None = None
    use_llm: bool = True
    use_web_search: bool = False


class AssistantFocus(BaseModel):
    type: str = "global"
    job_id: int | None = None
    analysis: JobAnalysisResponse | None = None
    source_url: str | None = None


class AssistantChatRequest(BaseModel):
    message: str
    focus: AssistantFocus = Field(default_factory=AssistantFocus)
    session_id: int | None = None
    history: list[JobChatMessage] = Field(default_factory=list)
    use_llm: bool = True
    use_web_search: bool = False


class AssistantChatResponse(BaseModel):
    answer: str
    focus: AssistantFocus
    messages: list[JobChatMessage]
    session: GlobalChatSession | None = None
    responder_used: str
    responder_warning: str | None = None
    used_web_search: bool = False
    citations: list[dict[str, str]] = Field(default_factory=list)


class GlobalChatRequest(BaseModel):
    message: str
    session_id: int | None = None
    use_llm: bool = True
    use_web_search: bool = False


class GlobalChatResponse(BaseModel):
    answer: str
    session: GlobalChatSession
    messages: list[GlobalChatMessage]
    responder_used: str
    responder_warning: str | None = None
    used_web_search: bool = False
    citations: list[dict[str, str]] = Field(default_factory=list)
    actions: list[AgentTask] = Field(default_factory=list)


class JobSearchCoordinator:
    def __init__(
        self,
        profile_store: ProfileStore | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.profile_store = profile_store or ProfileStore()
        self.repository = repository or JobRepository()

    def analyze(self, request: JobAnalysisRequest) -> JobAnalysisResponse:
        profile = self.profile_store.load()
        compacted_text = compact_job_text(request.description)
        analysis_text = compacted_text.text
        deterministic_job = parse_job_description(
            analysis_text,
            source_url=request.source_url,
            page_title=request.page_title,
        )
        parsed_job = deterministic_job
        parser_used = "deterministic"
        parser_warning = None

        if request.use_llm:
            try:
                if compacted_text.was_compacted:
                    parsed_job = parse_large_job_with_llm(
                        request.description,
                        deterministic_job=deterministic_job,
                        source_url=request.source_url,
                        page_title=request.page_title,
                        final_description=analysis_text,
                        extracted_posting=request.extracted_posting,
                    )
                    parser_used = "llm_chunked"
                else:
                    parsed_job = parse_job_with_llm(
                        analysis_text,
                        deterministic_job=deterministic_job,
                        source_url=request.source_url,
                        page_title=request.page_title,
                        extracted_posting=request.extracted_posting,
                    )
                    parser_used = "llm"
            except LLMJobParserUnavailable as error:
                parser_warning = str(error)

        fit = score_job_fit_with_llm(
            profile=profile,
            job=parsed_job,
        )
        scorer_used = "llm"

        guidance = JobApplicationGuidance()
        guidance_used = "disabled"
        guidance_warning = None

        if request.use_llm_guidance:
            try:
                guidance = generate_job_guidance_with_llm(
                    profile=profile,
                    job=parsed_job,
                    fit=fit,
                )
                guidance_used = "llm"
            except LLMJobGuidanceUnavailable as error:
                guidance_used = "unavailable"
                guidance_warning = str(error)

        response = JobAnalysisResponse(
            extracted_posting=request.extracted_posting,
            parsed_job=parsed_job,
            fit=fit,
            parser_used=parser_used,
            parser_warning=parser_warning,
            scorer_used=scorer_used,
            guidance=guidance,
            guidance_used=guidance_used,
            guidance_warning=guidance_warning,
            resume_emphasis=guidance.resume_guidance,
            prep_topics=guidance.prep_plan,
        )

        if request.save:
            provenance = _analysis_provenance(response)
            response.saved_job = self.repository.save_job(
                JobRecord(
                    title=parsed_job.title,
                    source_url=request.source_url,
                    company=parsed_job.company,
                    location=parsed_job.location,
                    description=parsed_job.description,
                    skills=parsed_job.skills,
                    fit_score=fit.score,
                    priority=fit.priority,
                    status=ApplicationStatus.DISCOVERED,
                    application_type=_classify_application_type(profile, parsed_job.company, request.source_url),
                    analysis=response.model_dump(exclude={"saved_job"}),
                    analysis_provenance=provenance,
                )
            )

        return response

    def save_analysis(self, analysis: JobAnalysisResponse, source_url: str | None = None) -> JobRecord:
        parsed_job = analysis.parsed_job
        profile = self.profile_store.load()
        return self.repository.save_job(
            JobRecord(
                title=parsed_job.title,
                source_url=source_url,
                company=parsed_job.company,
                location=parsed_job.location,
                description=parsed_job.description,
                skills=parsed_job.skills,
                fit_score=analysis.fit.score,
                priority=analysis.fit.priority,
                status=ApplicationStatus.DISCOVERED,
                application_type=_classify_application_type(profile, parsed_job.company, source_url),
                analysis=analysis.model_dump(exclude={"saved_job"}),
                analysis_provenance=_analysis_provenance(analysis),
            )
        )

    def update_saved_job_analysis(
        self,
        job_id: int,
        analysis: JobAnalysisResponse,
        source_url: str | None = None,
    ) -> JobRecord | None:
        parsed_job = analysis.parsed_job
        profile = self.profile_store.load()
        return self.repository.update_job_analysis(
            job_id,
            JobRecord(
                title=parsed_job.title,
                source_url=source_url,
                company=parsed_job.company,
                location=parsed_job.location,
                description=parsed_job.description,
                skills=parsed_job.skills,
                fit_score=analysis.fit.score,
                priority=analysis.fit.priority,
                application_type=_classify_application_type(profile, parsed_job.company, source_url),
                analysis=analysis.model_dump(exclude={"saved_job"}),
                analysis_provenance=_analysis_provenance(analysis),
            ),
        )

    def chat_about_job(self, job_id: int, request: JobChatRequest) -> JobChatResponse | None:
        detail = self.repository.get_job(job_id)
        if detail is None:
            return None

        self.repository.add_chat_message(
            JobChatMessage(
                job_id=job_id,
                role=ChatRole.USER,
                content=request.message.strip(),
            )
        )
        messages = [*self.repository.list_chat_messages(job_id)]

        answer = _fallback_chat_answer(detail.analysis, detail.job.title, request.message, request.use_web_search)
        citations: list[dict[str, str]] = []
        responder_used = "deterministic"
        responder_warning = None

        if request.use_llm:
            try:
                chat_answer = answer_job_chat_with_llm(
                    profile=self.profile_store.load(),
                    detail=detail,
                    messages=messages,
                    use_web_search=request.use_web_search,
                )
                answer = chat_answer.answer
                citations = chat_answer.citations
                responder_used = "llm"
            except LLMJobChatUnavailable as error:
                responder_warning = str(error)

        assistant_message = self.repository.add_chat_message(
            JobChatMessage(
                job_id=job_id,
                role=ChatRole.ASSISTANT,
                content=answer,
                used_web_search=request.use_web_search and responder_used == "llm",
                citations=citations,
            )
        )

        return JobChatResponse(
            answer=answer,
            messages=[*messages, assistant_message],
            responder_used=responder_used,
            responder_warning=responder_warning,
            used_web_search=assistant_message.used_web_search,
            citations=assistant_message.citations,
        )

    def chat_about_analysis(self, request: AnalysisChatRequest) -> JobChatResponse:
        analysis = request.analysis
        parsed_job = analysis.parsed_job
        user_message = JobChatMessage(
            id=None,
            job_id=0,
            role=ChatRole.USER,
            content=request.message.strip(),
        )
        messages = [*request.history, user_message]
        detail = JobDetail(
            job=JobRecord(
                id=0,
                source_url=request.source_url,
                title=parsed_job.title,
                company=parsed_job.company,
                location=parsed_job.location,
                description=parsed_job.description,
                skills=parsed_job.skills,
                fit_score=analysis.fit.score,
                priority=analysis.fit.priority,
                status=ApplicationStatus.DISCOVERED,
                analysis=analysis.model_dump(exclude={"saved_job"}),
            ),
            analysis=analysis.model_dump(exclude={"saved_job"}),
        )

        answer = _fallback_chat_answer(detail.analysis, detail.job.title, request.message, request.use_web_search)
        citations: list[dict[str, str]] = []
        responder_used = "deterministic"
        responder_warning = None

        if request.use_llm:
            try:
                chat_answer = answer_job_chat_with_llm(
                    profile=self.profile_store.load(),
                    detail=detail,
                    messages=messages,
                    use_web_search=request.use_web_search,
                )
                answer = chat_answer.answer
                citations = chat_answer.citations
                responder_used = "llm"
            except LLMJobChatUnavailable as error:
                responder_warning = str(error)

        assistant_message = JobChatMessage(
            id=None,
            job_id=0,
            role=ChatRole.ASSISTANT,
            content=answer,
            used_web_search=request.use_web_search and responder_used == "llm",
            citations=citations,
        )

        return JobChatResponse(
            answer=answer,
            messages=[*messages, assistant_message],
            responder_used=responder_used,
            responder_warning=responder_warning,
            used_web_search=assistant_message.used_web_search,
            citations=assistant_message.citations,
        )

    def chat_with_focus(self, request: AssistantChatRequest) -> AssistantChatResponse | None:
        focus_type = request.focus.type
        if focus_type == "saved_job":
            if request.focus.job_id is None:
                return None
            response = self.chat_about_job(
                request.focus.job_id,
                JobChatRequest(
                    message=request.message,
                    use_llm=request.use_llm,
                    use_web_search=request.use_web_search,
                ),
            )
            if response is None:
                return None
            return AssistantChatResponse(
                answer=response.answer,
                focus=request.focus,
                messages=response.messages,
                responder_used=response.responder_used,
                responder_warning=response.responder_warning,
                used_web_search=response.used_web_search,
                citations=response.citations,
            )

        if focus_type == "analysis_preview":
            if request.focus.analysis is None:
                return None
            response = self.chat_about_analysis(
                AnalysisChatRequest(
                    analysis=request.focus.analysis,
                    message=request.message,
                    history=request.history,
                    source_url=request.focus.source_url,
                    use_llm=request.use_llm,
                    use_web_search=request.use_web_search,
                )
            )
            return AssistantChatResponse(
                answer=response.answer,
                focus=request.focus,
                messages=response.messages,
                responder_used=response.responder_used,
                responder_warning=response.responder_warning,
                used_web_search=response.used_web_search,
                citations=response.citations,
            )

        response = self.chat_globally(
            GlobalChatRequest(
                message=request.message,
                session_id=request.session_id,
                use_llm=request.use_llm,
                use_web_search=request.use_web_search,
            )
        )
        return AssistantChatResponse(
            answer=response.answer,
            focus=AssistantFocus(type="global"),
            messages=[
                JobChatMessage(
                    id=message.id,
                    job_id=0,
                    role=message.role,
                    content=message.content,
                    used_web_search=message.used_web_search,
                    citations=message.citations,
                    created_at=message.created_at,
                )
                for message in response.messages
            ],
            session=response.session,
            responder_used=response.responder_used,
            responder_warning=response.responder_warning,
            used_web_search=response.used_web_search,
            citations=response.citations,
        )

    def chat_globally(self, request: GlobalChatRequest) -> GlobalChatResponse:
        session = (
            self.repository.get_global_chat_session(request.session_id)
            if request.session_id is not None
            else self.repository.create_global_chat_session(_chat_title_from_message(request.message))
        )
        if session is None:
            session = self.repository.create_global_chat_session(_chat_title_from_message(request.message))

        self.repository.add_global_chat_message(
            GlobalChatMessage(
                session_id=session.id,
                role=ChatRole.USER,
                content=request.message.strip(),
            )
        )
        messages = [*self.repository.list_global_chat_messages(session.id)]
        jobs = self.repository.list_jobs()
        profile_updates = extract_profile_updates_from_message(request.message)
        if profile_updates:
            self.profile_store.apply_updates(profile_updates, source="assistant_chat")
            answer = _profile_update_answer(profile_updates)
            assistant_message = self.repository.add_global_chat_message(
                GlobalChatMessage(
                    session_id=session.id,
                    role=ChatRole.ASSISTANT,
                    content=answer,
                )
            )
            return GlobalChatResponse(
                answer=answer,
                session=self.repository.get_global_chat_session(session.id) or session,
                messages=[*messages, assistant_message],
                responder_used="profile_update",
                used_web_search=False,
                citations=[],
            )

        answer = _fallback_global_chat_answer(jobs, request.message, request.use_web_search)
        citations: list[dict[str, str]] = []
        responder_used = "deterministic"
        responder_warning = None

        if request.use_llm:
            try:
                chat_answer = answer_global_chat_with_llm(
                    profile=self.profile_store.load(),
                    jobs=jobs,
                    messages=messages,
                    use_web_search=request.use_web_search,
                )
                answer = chat_answer.answer
                citations = chat_answer.citations
                responder_used = "llm"
            except LLMGlobalChatUnavailable as error:
                responder_warning = str(error)

        assistant_message = self.repository.add_global_chat_message(
            GlobalChatMessage(
                session_id=session.id,
                role=ChatRole.ASSISTANT,
                content=answer,
                used_web_search=request.use_web_search and responder_used == "llm",
                citations=citations,
            )
        )

        return GlobalChatResponse(
            answer=answer,
            session=self.repository.get_global_chat_session(session.id) or session,
            messages=[*messages, assistant_message],
            responder_used=responder_used,
            responder_warning=responder_warning,
            used_web_search=assistant_message.used_web_search,
            citations=assistant_message.citations,
        )


def _analysis_provenance(analysis: JobAnalysisResponse):
    used_llm = "llm" in {analysis.parser_used, analysis.scorer_used, analysis.guidance_used} or analysis.parser_used == "llm_chunked"
    return artifact_provenance(
        generator="llm" if used_llm else "deterministic",
        workflow_version=JOB_ANALYSIS_WORKFLOW_VERSION,
        schema_version=5,
        prompt_version=JOB_ANALYSIS_PROMPT_VERSION if used_llm else None,
        model=configured_llm_model(DEFAULT_LLM_MODEL) if used_llm else None,
    )


def _profile_update_answer(updates: dict[str, list[str]]) -> str:
    lines = ["Updated your local profile memory with:"]
    for key, values in updates.items():
        label = key.replace("_", " ").title()
        for value in values:
            lines.append(f"- {label}: {value}")
    lines.append("")
    lines.append("This was saved locally to `profile.local.yaml` and recorded in the profile audit log.")
    return "\n".join(lines)


def _classify_application_type(profile: dict, job_company: str | None, source_url: str | None = None) -> ApplicationType:
    current_company = (profile.get("current_role") or {}).get("company")
    if not current_company or not job_company:
        return ApplicationType.UNKNOWN

    current = _company_identity(str(current_company))
    target = _company_identity(job_company)
    if current and target and current == target:
        return ApplicationType.INTERNAL_TRANSFER

    if current == "amazon" and source_url and "amazon.jobs" in source_url.lower():
        return ApplicationType.INTERNAL_TRANSFER

    return ApplicationType.EXTERNAL_APPLICATION


def _company_identity(company: str) -> str:
    normalized = "".join(character for character in company.lower() if character.isalnum())
    aliases = {
        "amazonwebservices": "amazon",
        "aws": "amazon",
        "amazon": "amazon",
        "amazoncom": "amazon",
        "metaplatforms": "meta",
        "facebook": "meta",
        "meta": "meta",
        "googlellc": "google",
        "google": "google",
        "alphabet": "google",
        "microsoftcorporation": "microsoft",
        "microsoft": "microsoft",
    }
    return aliases.get(normalized, normalized)


def _chat_title_from_message(message: str) -> str:
    words = message.strip().split()
    if not words:
        return "New chat"
    return " ".join(words[:8])[:80]


def _fallback_chat_answer(analysis: dict | None, job_title: str | None, question: str, use_web_search: bool = False) -> str:
    if use_web_search:
        return (
            "Web search was requested, but the LLM web-search path is not available right now. Check that "
            "`OPENAI_API_KEY` is set and the OpenAI SDK is installed, then try again."
        )

    if not analysis:
        return (
            "I do not have a saved analysis payload for this job yet. Re-analyze the job first, then I can answer "
            "follow-up questions using the persisted fit, gaps, prep plan, and resume guidance."
        )

    fit = analysis.get("fit", {})
    guidance = analysis.get("guidance", {})
    parsed_job = analysis.get("parsed_job", {})
    title = job_title or analysis.get("parsed_job", {}).get("title") or "this role"
    gaps = fit.get("gaps") or []
    concerns = fit.get("concerns") or []
    apply_reasoning = guidance.get("apply_reasoning") or []
    prep_plan = guidance.get("prep_plan") or []
    resume_guidance = guidance.get("resume_guidance") or []
    interview_focus = guidance.get("interview_focus") or []
    role_signals = _merge_text_lists(
        parsed_job.get("role_focus") or [],
        parsed_job.get("requirements") or [],
        parsed_job.get("responsibilities") or [],
    )
    summary = fit.get("summary") or "I have a saved analysis for this role."

    lowered = question.lower()
    if any(keyword in lowered for keyword in ["why", "reason", "worth", "apply"]):
        items = apply_reasoning[:4] or [summary]
        return f"For {title}, the apply rationale I have is: " + " ".join(f"- {item}" for item in items)

    if any(keyword in lowered for keyword in ["concern", "risk", "wrong", "unsupported"]):
        if concerns:
            return f"For {title}, the saved concerns/risks are: " + " ".join(f"- {item}" for item in concerns[:5])
        return f"I do not see saved concerns for {title}. If a concern looks wrong, mark it as feedback so we can turn it into an eval case."

    if "resume" in lowered:
        items = resume_guidance[:4] or ["Tie your backend, cloud, and workflow experience directly to the job requirements."]
        return f"For {title}, I would position your resume around: " + " ".join(f"- {item}" for item in items)

    if "interview" in lowered:
        items = interview_focus[:4] or prep_plan[:4] or ["Prepare backend system design, operational ownership, and role-specific technical gaps."]
        return f"For {title}, interview prep should focus on: " + " ".join(f"- {item}" for item in items)

    if "prepare" in lowered or "prep" in lowered or "learn" in lowered or "plan" in lowered:
        items = prep_plan[:4] or [f"Review the role gaps first: {', '.join(gaps[:3])}."]
        return f"For {title}, start with this prep sequence: " + " ".join(f"- {item}" for item in items)

    if "gap" in lowered or "missing" in lowered:
        if gaps:
            return f"The main gaps I have saved for {title} are: {', '.join(gaps[:5])}."
        return f"I do not see saved skill gaps for {title}. Re-run analysis with LLM scoring if this seems wrong."

    if any(keyword in lowered for keyword in ["requirement", "responsibility", "role", "team", "business"]):
        if role_signals:
            return f"For {title}, the strongest saved role signals are: " + " ".join(f"- {item}" for item in role_signals[:5])
        return f"I do not have detailed role signals saved for {title}; re-run analysis if the current extraction looks too thin."

    return f"Saved analysis summary for {title}: {summary}"


def _fallback_global_chat_answer(jobs: list[JobRecord], question: str, use_web_search: bool = False) -> str:
    if use_web_search:
        return (
            "Web search was requested, but the LLM web-search path is not available right now. Check that "
            "`OPENAI_API_KEY` is set and the OpenAI SDK is installed, then try again."
        )

    if not jobs:
        return "You do not have saved jobs yet. Start by analyzing one target role, then I can compare jobs and suggest next actions."

    lowered = question.lower()
    active_jobs = [job for job in jobs if job.status.value not in {"rejected", "offer"}]
    top_jobs = sorted(jobs, key=lambda job: job.fit_score, reverse=True)[:3]
    all_gaps = []
    all_prep = []
    for job in jobs:
        analysis = job.analysis or {}
        fit = analysis.get("fit") or {}
        guidance = analysis.get("guidance") or {}
        all_gaps.extend(fit.get("gaps") or [])
        all_prep.extend(guidance.get("prep_plan") or [])

    if "rank" in lowered or "compare" in lowered or "best" in lowered:
        ranked = "; ".join(
            f"{job.title or 'Untitled role'} at {job.company or 'Unknown company'} ({job.fit_score}, {job.priority})"
            for job in top_jobs
        )
        return f"Based on saved fit scores, your strongest current targets are: {ranked}."

    if "gap" in lowered or "missing" in lowered or "skill" in lowered:
        gaps = _top_repeated_items(all_gaps)
        if gaps:
            return "Across saved jobs, the repeated gaps I see are: " + "; ".join(gaps[:6]) + "."
        return "I do not see saved gap data yet. Re-analyze your target jobs with LLM scoring enabled to populate richer gap signals."

    if "resume" in lowered:
        return (
            "For resume work, pick one saved target role first, then generate a role-targeted draft from that job. "
            "The safest positioning is to emphasize truthful backend, workflow orchestration, cloud, and distributed-systems ownership."
        )

    if "next" in lowered or "plan" in lowered or "prepare" in lowered:
        prep_items = _top_repeated_items(all_prep)
        if prep_items:
            return "A practical next prep sequence from saved jobs is: " + " ".join(f"- {item}" for item in prep_items[:5])
        return (
            f"You have {len(active_jobs)} active saved jobs. I would pick the highest-fit role, refresh its analysis if needed, "
            "then create a prep plan from its gaps and resume guidance. Use web search only for company-specific prep."
        )

    if "status" in lowered or "applied" in lowered or "application" in lowered:
        status_counts = {}
        for job in jobs:
            status_counts[job.status.value] = status_counts.get(job.status.value, 0) + 1
        summary = ", ".join(f"{status}: {count}" for status, count in sorted(status_counts.items()))
        return f"Your saved application status summary is: {summary}."

    return (
        f"You have {len(jobs)} saved jobs, with {len(active_jobs)} still active. Ask me to rank them, compare gaps, "
        "or build a prep plan from your saved applications."
    )


def _merge_text_lists(*lists: list[str]) -> list[str]:
    result = []
    seen = set()
    for values in lists:
        for value in values:
            cleaned = value.strip()
            if cleaned and cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                result.append(cleaned)
    return result


def _top_repeated_items(items: list[str]) -> list[str]:
    counts: dict[str, tuple[str, int]] = {}
    for item in items:
        cleaned = item.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        label, count = counts.get(key, (cleaned, 0))
        counts[key] = (label, count + 1)
    return [label for label, _count in sorted(counts.values(), key=lambda value: (-value[1], value[0].lower()))]
