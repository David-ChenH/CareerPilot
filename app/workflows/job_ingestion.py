from typing import Any

from app.agents.coordinator import JobAnalysisRequest, JobSearchCoordinator
from app.db.models import AgentTaskStatus
from app.workflows import WorkflowDefinition, WorkflowExecutor, WorkflowTask, WorkflowToolRegistry
from app.workflows.graph import workflow_graph_from_run
from app.workflows.models import WorkflowRun
from app.workflows.trace import WorkflowTraceEvent


def build_job_ingestion_workflow(request) -> WorkflowDefinition:
    """Build the approved DAG template for background job-link ingestion.

    The planner is deterministic in this stage: product code chooses the allowed
    workflow shape, and the executor handles dependency order, output passing,
    trace events, and failure blocking.
    """
    tasks = [
        WorkflowTask(
            id="fetch_job",
            tool="fetch_job",
            description="Fetch readable job text from the source link.",
            input={
                "url": request.url,
                "use_browser_fallback": request.use_browser_fallback,
            },
        ),
        WorkflowTask(
            id="analyze_job",
            tool="analyze_job",
            description="Parse, score, and generate guidance.",
            dependencies=["fetch_job"],
            input={
                "use_llm": request.use_llm,
                "use_llm_guidance": request.use_llm_guidance,
            },
        ),
    ]
    if request.save:
        tasks.append(
            WorkflowTask(
                id="save_job",
                tool="save_job",
                description="Persist reviewed analysis into the application tracker.",
                dependencies=["fetch_job", "analyze_job"],
            )
        )
    return WorkflowDefinition(
        id="job_ingestion",
        version=1,
        description="Fetch a job link, analyze it, and optionally save it to the tracker.",
        tasks=tasks,
    )


class JobIngestionWorkflowRunner:
    """Adapter between the generic workflow runtime and CareerPilot job tools."""

    def __init__(
        self,
        *,
        coordinator: JobSearchCoordinator,
        fetch_job_description,
        fetch_summary,
    ) -> None:
        self.coordinator = coordinator
        self.fetch_job_description = fetch_job_description
        self.fetch_summary = fetch_summary

    def run(self, task_id: str, request) -> None:
        self.coordinator.repository.update_agent_task(task_id, status=AgentTaskStatus.RUNNING)
        workflow = build_job_ingestion_workflow(request)
        registry = WorkflowToolRegistry()
        # The registry is the autonomy boundary: the executor can only run tools
        # product code explicitly exposes here, never arbitrary model-generated code.
        registry.register("fetch_job", self._fetch_job)
        registry.register("analyze_job", lambda task_input, dependency_outputs: self._analyze_job(task_id, task_input, dependency_outputs))
        registry.register("save_job", self._save_job)
        run = WorkflowExecutor(registry).execute(
            workflow,
            on_event=lambda event, _run, task, output: self._sync_event_to_agent_task(
                task_id,
                event,
                task,
                output,
            ),
        )
        self._sync_run_to_agent_task(task_id, run)

    def _fetch_job(self, task_input: dict, _dependency_outputs: dict[str, Any]) -> dict:
        fetched_page, compacted_text = self.fetch_job_description(
            task_input["url"],
            task_input["use_browser_fallback"],
        )
        return {
            "fetched_page": fetched_page,
            "compacted_text": compacted_text,
            "description": compacted_text.text,
            "summary": self.fetch_summary(fetched_page.url, compacted_text, fetched_page.extraction_source),
            "artifacts": {
                "source_url": fetched_page.url,
                "page_title": fetched_page.title,
                "extraction_source": fetched_page.extraction_source,
                "extraction_recipe": getattr(fetched_page, "extraction_recipe", None),
                "extraction_strategy": fetched_page.extraction_strategy.model_dump(mode="json")
                if getattr(fetched_page, "extraction_strategy", None)
                else None,
                "extracted_posting": fetched_page.extracted_posting.model_dump(mode="json")
                if fetched_page.extracted_posting
                else None,
                "description_length": compacted_text.compacted_length,
                "original_description_length": compacted_text.original_length,
                "description_compacted": compacted_text.was_compacted,
            },
        }

    def _analyze_job(self, task_id: str, task_input: dict, dependency_outputs: dict[str, Any]) -> dict:
        fetch_output = dependency_outputs["fetch_job"]
        fetched_page = fetch_output["fetched_page"]
        analysis = self.coordinator.analyze(
            JobAnalysisRequest(
                description=fetch_output["description"],
                extracted_posting=fetched_page.extracted_posting,
                save=False,
                source_url=fetched_page.url,
                page_title=fetched_page.title,
                use_llm=task_input["use_llm"],
                use_llm_guidance=task_input["use_llm_guidance"],
            ),
            on_workflow_event=lambda event, _run, task, output: self._sync_analysis_event_to_agent_task(
                task_id,
                event,
                task,
                output,
            ),
        )
        return {
            "analysis": analysis,
            "summary": f"Analysis produced {analysis.fit.priority} priority with score {analysis.fit.score}.",
            "artifacts": {"analysis": analysis.model_dump(exclude={"saved_job"}, mode="json")},
        }

    def _save_job(self, _task_input: dict, dependency_outputs: dict[str, Any]) -> dict:
        analysis = dependency_outputs["analyze_job"]["analysis"]
        fetched_page = dependency_outputs["fetch_job"]["fetched_page"]
        saved_job = self.coordinator.save_analysis(analysis, source_url=fetched_page.url)
        return {
            "saved_job": saved_job,
            "summary": f"Saved {saved_job.title or 'untitled job'} as {saved_job.application_type.value}.",
            "artifacts": {"saved_job": saved_job.model_dump(mode="json")},
        }

    def _sync_event_to_agent_task(
        self,
        task_id: str,
        event: WorkflowTraceEvent,
        task,
        output: dict | None,
    ) -> None:
        """Project runtime trace events into the persisted task progress model.

        `WorkflowRun` is the platform runtime record. `AgentTask` is the
        product-facing progress record already used by the API and frontend.
        Keeping this bridge explicit avoids leaking executor internals into UI
        persistence.
        """
        if event.event == "started":
            self.coordinator.repository.start_agent_task_step(task_id, task.id, task.description)
        elif event.event == "completed":
            output = output or {}
            self.coordinator.repository.complete_agent_task_step(task_id, task.id, output.get("summary"))
            if output.get("artifacts"):
                self.coordinator.repository.update_agent_task(task_id, artifacts=output["artifacts"])
        elif event.event == "failed":
            self.coordinator.repository.fail_agent_task_step(
                task_id,
                task.id,
                event.detail or task.error_type or "Workflow task failed.",
            )
        elif event.event == "blocked":
            self.coordinator.repository.fail_agent_task_step(
                task_id,
                task.id,
                event.detail or "Blocked by failed dependency.",
            )

    def _sync_analysis_event_to_agent_task(
        self,
        task_id: str,
        event: WorkflowTraceEvent,
        task,
        output: dict | None,
    ) -> None:
        """Expose nested analysis progress while the outer analyze step runs.

        Link ingestion is one user-facing workflow, but job analysis itself has
        meaningful internal stages. Projecting those stages as prefixed steps
        gives the UI a heartbeat during slow LLM calls without coupling the
        frontend to coordinator internals.
        """
        step_name = f"analysis_{task.id}"
        if event.event == "started":
            self.coordinator.repository.start_agent_task_step(task_id, step_name, task.description)
        elif event.event == "completed":
            output = output or {}
            self.coordinator.repository.complete_agent_task_step(task_id, step_name, output.get("summary"))
        elif event.event == "failed":
            self.coordinator.repository.fail_agent_task_step(
                task_id,
                step_name,
                event.detail or task.error_type or "Analysis stage failed.",
            )
        elif event.event == "blocked":
            self.coordinator.repository.fail_agent_task_step(
                task_id,
                step_name,
                event.detail or "Blocked by failed analysis dependency.",
            )

    def _sync_run_to_agent_task(self, task_id: str, run: WorkflowRun) -> None:
        self.coordinator.repository.update_agent_task(
            task_id,
            status=AgentTaskStatus.COMPLETED if run.status == "completed" else AgentTaskStatus.FAILED,
            artifacts={
                "workflow_graph": workflow_graph_from_run(run).model_dump(mode="json"),
                "workflow_run": run.model_dump(exclude={"outputs"}, mode="json"),
            },
            error=_workflow_error(run),
        )


def _workflow_error(run: WorkflowRun) -> str | None:
    if run.status == "completed":
        return None
    failed = next((task for task in run.tasks if task.status == "failed"), None)
    if failed:
        failed_events = [
            event for event in run.trace_events if event.task_id == failed.id and event.event == "failed"
        ]
        if failed_events and failed_events[-1].detail:
            return failed_events[-1].detail
        return failed.error_type or "Workflow task failed."
    return "Workflow failed."
