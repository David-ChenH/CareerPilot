from typing import Any

from pydantic import BaseModel, Field

from app.artifacts import PREP_PLAN_WORKFLOW_VERSION
from app.db.models import JobRecord, LeetCodeProblem, PrepPlan
from app.memory.profile_schema import ProfileV1
from app.tools.prep_planner import generate_prep_plan, generate_prep_plan_with_llm
from app.workflows import ModelTier, WorkflowDefinition, WorkflowTask, WorkflowToolRegistry
from app.workflows.graph import workflow_graph_from_run
from app.workflows.models import WorkflowRun
from app.workflows.runtime import NativeWorkflowRuntime, WorkflowRuntime


class PrepPlanWorkflowRequest(BaseModel):
    timeline_days: int = Field(default=14, ge=1, le=90)
    hours_per_day: float = Field(default=2, ge=0.5, le=12)
    focus: str | None = None
    job_id: int | None = None
    use_llm: bool = True


def build_prep_plan_workflow(request: PrepPlanWorkflowRequest) -> WorkflowDefinition:
    """Build the approved DAG template for interview-preparation planning.

    This workflow is still deterministic in shape. The agentic behavior lives in
    tool outputs and LLM-backed generation/evaluation, while product code owns
    which tools may run and how data moves between them.
    """
    return WorkflowDefinition(
        id="prep_plan_generation",
        version=1,
        description="Generate a preparation plan from profile, target job, coding practice state, and timeline.",
        tasks=[
            WorkflowTask(
                id="plan_prep_workflow",
                tool="plan_prep_workflow",
                description="Normalize the user goal, timeline, and preparation constraints.",
                input=request.model_dump(mode="json"),
                model_tier=ModelTier.NONE,
            ),
            WorkflowTask(
                id="analyze_profile",
                tool="analyze_profile",
                description="Summarize profile strengths, learning goals, and target direction.",
                dependencies=["plan_prep_workflow"],
                model_tier=ModelTier.NONE,
            ),
            WorkflowTask(
                id="analyze_target_job",
                tool="analyze_target_job",
                description="Summarize selected job context and saved-job signals.",
                dependencies=["plan_prep_workflow"],
                model_tier=ModelTier.NONE,
            ),
            WorkflowTask(
                id="analyze_coding_practice",
                tool="analyze_coding_practice",
                description="Summarize coding-practice state from the local practice dashboard.",
                dependencies=["plan_prep_workflow"],
                model_tier=ModelTier.NONE,
            ),
            WorkflowTask(
                id="identify_skill_gaps",
                tool="identify_skill_gaps",
                description="Combine profile and job context into preparation gap signals.",
                dependencies=["analyze_profile", "analyze_target_job"],
                model_tier=ModelTier.STANDARD if request.use_llm else ModelTier.NONE,
            ),
            WorkflowTask(
                id="generate_learning_plan",
                tool="generate_learning_plan",
                description="Generate learning topics from gaps and user focus.",
                dependencies=["identify_skill_gaps"],
                model_tier=ModelTier.STANDARD if request.use_llm else ModelTier.NONE,
            ),
            WorkflowTask(
                id="generate_coding_plan",
                tool="generate_coding_plan",
                description="Generate coding-practice topics from gaps and practice state.",
                dependencies=["identify_skill_gaps", "analyze_coding_practice"],
                model_tier=ModelTier.STANDARD if request.use_llm else ModelTier.NONE,
            ),
            WorkflowTask(
                id="generate_system_design_plan",
                tool="generate_system_design_plan",
                description="Generate system-design practice topics from role and profile signals.",
                dependencies=["identify_skill_gaps"],
                model_tier=ModelTier.STANDARD if request.use_llm else ModelTier.NONE,
            ),
            WorkflowTask(
                id="evaluate_prep_plan",
                tool="evaluate_prep_plan",
                description="Validate branch outputs before final aggregation.",
                dependencies=["generate_learning_plan", "generate_coding_plan", "generate_system_design_plan"],
                model_tier=ModelTier.NONE,
            ),
            WorkflowTask(
                id="aggregate_plan",
                tool="aggregate_plan",
                description="Aggregate branch outputs into the final persisted prep plan.",
                dependencies=[
                    "plan_prep_workflow",
                    "analyze_profile",
                    "analyze_target_job",
                    "analyze_coding_practice",
                    "identify_skill_gaps",
                    "generate_learning_plan",
                    "generate_coding_plan",
                    "generate_system_design_plan",
                    "evaluate_prep_plan",
                ],
                model_tier=ModelTier.STRONG if request.use_llm else ModelTier.NONE,
            ),
        ],
    )


class PrepPlanWorkflowRunner:
    """Adapter between the generic workflow runtime and CareerPilot prep tools."""

    def __init__(
        self,
        *,
        profile: ProfileV1,
        jobs: list[JobRecord],
        coding_problems: list[LeetCodeProblem],
        runtime: WorkflowRuntime | None = None,
    ) -> None:
        self.profile = profile
        self.jobs = jobs
        self.coding_problems = coding_problems
        self.runtime = runtime or NativeWorkflowRuntime()

    def run(self, request: PrepPlanWorkflowRequest) -> PrepPlan:
        workflow = build_prep_plan_workflow(request)
        registry = WorkflowToolRegistry()
        registry.register("plan_prep_workflow", self._plan_prep_workflow)
        registry.register("analyze_profile", self._analyze_profile)
        registry.register("analyze_target_job", self._analyze_target_job)
        registry.register("analyze_coding_practice", self._analyze_coding_practice)
        registry.register("identify_skill_gaps", self._identify_skill_gaps)
        registry.register("generate_learning_plan", self._generate_learning_plan)
        registry.register("generate_coding_plan", self._generate_coding_plan)
        registry.register("generate_system_design_plan", self._generate_system_design_plan)
        registry.register("evaluate_prep_plan", self._evaluate_prep_plan)
        registry.register("aggregate_plan", self._aggregate_plan)

        run = self.runtime.execute(workflow, registry)
        if "aggregate_plan" not in run.outputs:
            raise RuntimeError(_workflow_error(run))
        plan: PrepPlan = run.outputs["aggregate_plan"]["plan"]
        plan.workflow_graph = workflow_graph_from_run(run).model_dump(mode="json")
        plan.workflow_run = run.model_dump(exclude={"outputs"}, mode="json")
        plan.evaluation = run.outputs.get("evaluate_prep_plan")
        return plan

    def _plan_prep_workflow(self, task_input: dict, _dependency_outputs: dict[str, Any]) -> dict:
        request = PrepPlanWorkflowRequest(**task_input)
        return {
            "timeline_days": request.timeline_days,
            "hours_per_day": request.hours_per_day,
            "focus": request.focus,
            "job_id": request.job_id,
            "use_llm": request.use_llm,
            "summary": f"{request.timeline_days} days at {request.hours_per_day:g} hours/day.",
        }

    def _analyze_profile(self, _task_input: dict, _dependency_outputs: dict[str, Any]) -> dict:
        context = self.profile.to_runtime_context()
        return {
            "profile": self.profile,
            "runtime_context": context,
            "strengths": context.get("technical_strengths", [])[:10],
            "learning_goals": context.get("learning_goals", [])[:10],
            "target_roles": context.get("target_roles", [])[:10],
        }

    def _analyze_target_job(self, _task_input: dict, dependency_outputs: dict[str, Any]) -> dict:
        plan = dependency_outputs["plan_prep_workflow"]
        selected_job = next((job for job in self.jobs if job.id == plan.get("job_id")), None)
        saved_job_signals = [
            {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "skills": job.skills,
                "gaps": (job.analysis or {}).get("fit", {}).get("gaps", []),
                "growth_areas": (job.analysis or {}).get("fit", {}).get("growth_areas", []),
                "prep_plan": (job.analysis or {}).get("guidance", {}).get("prep_plan", []),
            }
            for job in self.jobs[:10]
        ]
        return {
            "selected_job": selected_job,
            "selected_job_summary": selected_job.model_dump(mode="json") if selected_job else None,
            "saved_job_signals": saved_job_signals,
        }

    def _analyze_coding_practice(self, _task_input: dict, _dependency_outputs: dict[str, Any]) -> dict:
        by_status: dict[str, int] = {}
        categories: dict[str, int] = {}
        for problem in self.coding_problems:
            by_status[problem.status.value] = by_status.get(problem.status.value, 0) + 1
            categories[problem.category] = categories.get(problem.category, 0) + 1
        return {
            "total": len(self.coding_problems),
            "by_status": by_status,
            "top_categories": sorted(categories, key=categories.get, reverse=True)[:8],
            "recent_notes": [
                {"title": problem.title, "category": problem.category, "tags": problem.tags, "note": problem.note}
                for problem in self.coding_problems[:10]
            ],
        }

    def _identify_skill_gaps(self, _task_input: dict, dependency_outputs: dict[str, Any]) -> dict:
        profile = dependency_outputs["analyze_profile"]
        job_context = dependency_outputs["analyze_target_job"]
        selected_job = job_context["selected_job"]
        gaps: list[str] = []
        growth_areas: list[str] = []
        prep_actions: list[str] = []
        if selected_job and selected_job.analysis:
            fit = selected_job.analysis.get("fit", {})
            guidance = selected_job.analysis.get("guidance", {})
            gaps.extend(fit.get("gaps", []))
            growth_areas.extend(fit.get("growth_areas", []))
            prep_actions.extend(guidance.get("prep_plan", []))
        else:
            for saved_job in job_context["saved_job_signals"]:
                gaps.extend(saved_job.get("gaps", [])[:2])
                growth_areas.extend(saved_job.get("growth_areas", [])[:2])
                prep_actions.extend(saved_job.get("prep_plan", [])[:2])
        return {
            "gaps": _dedupe(gaps),
            "growth_areas": _dedupe(growth_areas),
            "prep_actions": _dedupe(prep_actions),
            "profile_learning_goals": profile.get("learning_goals", []),
            "profile_strengths": profile.get("strengths", []),
        }

    def _generate_learning_plan(self, _task_input: dict, dependency_outputs: dict[str, Any]) -> dict:
        gaps = dependency_outputs["identify_skill_gaps"]
        topics = _dedupe(gaps["gaps"] + gaps["growth_areas"] + gaps["profile_learning_goals"])
        return {"topics": topics[:10], "summary": f"{len(topics[:10])} learning topics."}

    def _generate_coding_plan(self, _task_input: dict, dependency_outputs: dict[str, Any]) -> dict:
        gaps = dependency_outputs["identify_skill_gaps"]
        coding = dependency_outputs["analyze_coding_practice"]
        topics = _dedupe(
            coding.get("top_categories", [])
            + ["arrays and hash maps", "graphs or trees", "dynamic programming", "concurrency fundamentals"]
        )
        if any("distributed" in item.lower() for item in gaps["growth_areas"] + gaps["gaps"]):
            topics.append("system-design-adjacent coding: concurrency and data structures")
        return {"topics": topics[:8], "practice_count": coding["total"]}

    def _generate_system_design_plan(self, _task_input: dict, dependency_outputs: dict[str, Any]) -> dict:
        gaps = dependency_outputs["identify_skill_gaps"]
        topics = _dedupe(
            [
                "workflow orchestration and failure handling",
                "distributed storage and consistency tradeoffs",
                "queues, workers, retries, and idempotency",
                *gaps["growth_areas"],
            ]
        )
        return {"topics": topics[:8]}

    def _evaluate_prep_plan(self, _task_input: dict, dependency_outputs: dict[str, Any]) -> dict:
        branches = {
            "learning": dependency_outputs["generate_learning_plan"].get("topics", []),
            "coding": dependency_outputs["generate_coding_plan"].get("topics", []),
            "system_design": dependency_outputs["generate_system_design_plan"].get("topics", []),
        }
        warnings = [name for name, topics in branches.items() if not topics]
        return {
            "status": "pass" if not warnings else "warning",
            "warnings": [f"{name} branch produced no topics." for name in warnings],
            "branch_topic_counts": {name: len(topics) for name, topics in branches.items()},
        }

    def _aggregate_plan(self, _task_input: dict, dependency_outputs: dict[str, Any]) -> dict:
        plan_input = dependency_outputs["plan_prep_workflow"]
        profile_output = dependency_outputs["analyze_profile"]
        job_output = dependency_outputs["analyze_target_job"]
        focus = _combine_focus(
            plan_input.get("focus"),
            dependency_outputs["generate_learning_plan"].get("topics", []),
            dependency_outputs["generate_coding_plan"].get("topics", []),
            dependency_outputs["generate_system_design_plan"].get("topics", []),
        )
        if plan_input["use_llm"]:
            try:
                plan = generate_prep_plan_with_llm(
                    profile=profile_output["profile"],
                    jobs=self.jobs,
                    timeline_days=plan_input["timeline_days"],
                    hours_per_day=plan_input["hours_per_day"],
                    focus=focus,
                    job_id=plan_input.get("job_id"),
                )
            except Exception:
                plan = generate_prep_plan(
                    profile=profile_output["profile"],
                    jobs=self.jobs,
                    timeline_days=plan_input["timeline_days"],
                    hours_per_day=plan_input["hours_per_day"],
                    focus=focus,
                    job_id=plan_input.get("job_id"),
                )
                plan.source = "workflow_fallback"
        else:
            plan = generate_prep_plan(
                profile=profile_output["profile"],
                jobs=self.jobs,
                timeline_days=plan_input["timeline_days"],
                hours_per_day=plan_input["hours_per_day"],
                focus=focus,
                job_id=plan_input.get("job_id"),
            )
            plan.source = "workflow_generated"
        target = job_output.get("selected_job")
        summary = f"Generated {len(plan.days)} prep days"
        if target:
            summary += f" for {target.title}."
        else:
            summary += "."
        plan.provenance.workflow_version = PREP_PLAN_WORKFLOW_VERSION
        return {"plan": plan, "summary": summary}


def _combine_focus(original: str | None, *topic_groups: list[str]) -> str | None:
    values: list[str] = []
    if original:
        values.append(original)
    for group in topic_groups:
        values.extend(group)
    return ", ".join(_dedupe(values)) if values else None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _workflow_error(run: WorkflowRun) -> str:
    failed = next((task for task in run.tasks if task.status == "failed"), None)
    if failed:
        event = next(
            (
                trace
                for trace in reversed(run.trace_events)
                if trace.task_id == failed.id and trace.event == "failed" and trace.detail
            ),
            None,
        )
        return event.detail if event else failed.error_type or "Prep workflow failed."
    return "Prep workflow did not produce a final plan."
