import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent_skills import AgentSkillCatalog
from app.extraction_overrides.career_pages import CareerPageExtractionOverrideRegistry
from app.workflows import (
    ModelTier,
    WorkflowDefinition,
    WorkflowExecutionError,
    WorkflowExecutor,
    WorkflowGraphError,
    LangGraphRuntimeUnavailable,
    LangGraphWorkflowRuntime,
    NativeWorkflowRuntime,
    WorkflowRun,
    WorkflowRuntimeSelection,
    WorkflowTask,
    WorkflowToolRegistry,
    select_workflow_runtime,
    topological_groups,
    topological_order,
    validate_workflow,
    workflow_graph_from_definition,
)
from app.agents.coordinator import JobSearchCoordinator
from app.db.models import AgentTaskStatus, AgentTaskType, LeetCodeProblem
from app.db.repository import JobRepository
from app.memory.profile_store import ProfileStore
from app.tools.scoring import JobFit
from app.workflows.job_ingestion import JobIngestionWorkflowRunner, build_job_ingestion_workflow
from app.workflows.prep_plan import PrepPlanWorkflowRequest, PrepPlanWorkflowRunner, build_prep_plan_workflow


class _FakeStateGraph:
    def __init__(self, _state_type) -> None:
        self.nodes = {}
        self.edges = {}

    def add_node(self, name: str, handler) -> None:
        self.nodes[name] = handler

    def add_edge(self, source: str, target: str) -> None:
        self.edges[source] = target

    def compile(self):
        return _FakeCompiledGraph(self.nodes, self.edges)


class _FakeCompiledGraph:
    def __init__(self, nodes, edges) -> None:
        self.nodes = nodes
        self.edges = edges

    def invoke(self, state):
        current = self.edges["__start__"]
        while current != "__end__":
            state = self.nodes[current](state)
            current = self.edges[current]
        return state


class _UnavailableRuntime:
    name = "langgraph"

    def execute(self, *_args, **_kwargs):
        raise LangGraphRuntimeUnavailable("LangGraph runtime failed to initialize.")


def _prep_workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        id="interview-prep",
        tasks=[
            WorkflowTask(id="analyze_job", tool="analyze_job", model_tier=ModelTier.CHEAP),
            WorkflowTask(id="load_profile", tool="load_profile"),
            WorkflowTask(
                id="identify_gaps",
                tool="identify_gaps",
                dependencies=["analyze_job", "load_profile"],
                model_tier=ModelTier.STANDARD,
            ),
            WorkflowTask(id="learning_plan", tool="learning_plan", dependencies=["identify_gaps"]),
            WorkflowTask(id="coding_plan", tool="coding_plan", dependencies=["identify_gaps"]),
            WorkflowTask(
                id="aggregate",
                tool="aggregate",
                dependencies=["learning_plan", "coding_plan"],
            ),
        ],
    )


def test_loads_reviewed_microsoft_career_page_extraction_override() -> None:
    override = CareerPageExtractionOverrideRegistry().load("microsoft")

    assert override.domains == ["apply.careers.microsoft.com"]
    assert override.content_selector == "main"
    assert "qualifications" in override.quality_checks.expected_signals


def test_finds_career_page_extraction_override_by_url() -> None:
    override = CareerPageExtractionOverrideRegistry().find_for_url(
        "https://apply.careers.microsoft.com/careers/job/123?domain=microsoft.com"
    )

    assert override is not None
    assert override.content_selector == "main"


def test_rejects_malformed_career_page_extraction_override(tmp_path: Path) -> None:
    override_path = tmp_path / "broken"
    override_path.mkdir()
    (override_path / "override.yaml").write_text(
        "version: 1\ndomains: []\ncontent_selector: ''\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        CareerPageExtractionOverrideRegistry(tmp_path).load("broken")


def test_loads_framework_neutral_agent_skill() -> None:
    skill = AgentSkillCatalog().load("career_page_extraction")

    assert skill.metadata.id == "career_page_extraction"
    assert skill.metadata.capabilities == ["extract_job_posting"]
    assert "Never execute generated Python or JavaScript" in skill.instructions


def test_missing_agent_skill_is_rejected() -> None:
    with pytest.raises(FileNotFoundError):
        AgentSkillCatalog().load("missing")


def test_dag_returns_dependency_order_and_parallel_ready_groups() -> None:
    workflow = _prep_workflow()

    validate_workflow(workflow)

    assert topological_groups(workflow.tasks) == [
        ["analyze_job", "load_profile"],
        ["identify_gaps"],
        ["coding_plan", "learning_plan"],
        ["aggregate"],
    ]
    assert topological_order(workflow) == [
        "analyze_job",
        "load_profile",
        "identify_gaps",
        "coding_plan",
        "learning_plan",
        "aggregate",
    ]


def test_workflow_graph_serializes_nodes_and_edges() -> None:
    graph = workflow_graph_from_definition(_prep_workflow())

    assert graph.workflow_id == "interview-prep"
    assert graph.nodes[0].id == "analyze_job"
    assert graph.nodes[0].label == "analyze job"
    assert {"source": "analyze_job", "target": "identify_gaps"} in [
        edge.model_dump() for edge in graph.edges
    ]
    assert {"source": "coding_plan", "target": "aggregate"} in [
        edge.model_dump() for edge in graph.edges
    ]


def test_dag_rejects_duplicate_task_ids() -> None:
    workflow = WorkflowDefinition(
        id="duplicate",
        tasks=[
            WorkflowTask(id="same", tool="first"),
            WorkflowTask(id="same", tool="second"),
        ],
    )

    with pytest.raises(WorkflowGraphError, match="duplicate"):
        validate_workflow(workflow)


def test_dag_rejects_missing_dependency() -> None:
    workflow = WorkflowDefinition(
        id="missing",
        tasks=[WorkflowTask(id="aggregate", tool="aggregate", dependencies=["unknown"])],
    )

    with pytest.raises(WorkflowGraphError, match="unknown"):
        validate_workflow(workflow)


def test_dag_rejects_cycle() -> None:
    workflow = WorkflowDefinition(
        id="cycle",
        tasks=[
            WorkflowTask(id="first", tool="first", dependencies=["second"]),
            WorkflowTask(id="second", tool="second", dependencies=["first"]),
        ],
    )

    with pytest.raises(WorkflowGraphError, match="cycle"):
        validate_workflow(workflow)


def test_workflow_run_keeps_runtime_state_separate_from_definition() -> None:
    workflow = _prep_workflow()
    run = WorkflowRun(
        id="run-123",
        workflow_id=workflow.id,
        workflow_version=workflow.version,
        tasks=workflow.tasks,
    )

    assert run.outputs == {}
    assert run.total_estimated_cost_usd == 0
    assert run.tasks[0].status == "pending"


def test_executor_runs_dag_and_passes_dependency_outputs() -> None:
    registry = WorkflowToolRegistry()
    registry.register("load_profile", lambda _input, _dependencies: {"skills": ["Python"]})
    registry.register("analyze_job", lambda task_input, _dependencies: {"title": task_input["title"]})
    registry.register(
        "identify_gaps",
        lambda _input, dependencies: {
            "title": dependencies["analyze_job"]["title"],
            "skills": dependencies["load_profile"]["skills"],
        },
    )
    workflow = WorkflowDefinition(
        id="analysis",
        tasks=[
            WorkflowTask(id="load_profile", tool="load_profile"),
            WorkflowTask(id="analyze_job", tool="analyze_job", input={"title": "Backend Engineer"}),
            WorkflowTask(id="identify_gaps", tool="identify_gaps", dependencies=["load_profile", "analyze_job"]),
        ],
    )

    run = WorkflowExecutor(registry).execute(workflow)

    assert run.status == "completed"
    assert run.outputs["identify_gaps"] == {"title": "Backend Engineer", "skills": ["Python"]}
    assert [event.event for event in run.trace_events] == [
        "started",
        "completed",
        "started",
        "completed",
        "started",
        "completed",
    ]
    assert all(task.status == "pending" for task in workflow.tasks)


def test_executor_rejects_unknown_tools_before_running() -> None:
    workflow = WorkflowDefinition(id="unknown", tasks=[WorkflowTask(id="missing", tool="missing")])

    with pytest.raises(WorkflowExecutionError, match="unregistered"):
        WorkflowExecutor(WorkflowToolRegistry()).execute(workflow)


def test_native_workflow_runtime_wraps_existing_executor() -> None:
    registry = WorkflowToolRegistry()
    registry.register("identity", lambda task_input, _dependencies: task_input)
    workflow = WorkflowDefinition(
        id="native-runtime",
        tasks=[WorkflowTask(id="first", tool="identity", input={"ok": True})],
    )

    run = NativeWorkflowRuntime().execute(workflow, registry)

    assert run.status == "completed"
    assert run.outputs["first"] == {"ok": True}


def test_langgraph_runtime_runs_approved_workflow_with_same_outputs(monkeypatch) -> None:
    fake_langgraph = ModuleType("langgraph")
    fake_graph = ModuleType("langgraph.graph")
    fake_graph.START = "__start__"
    fake_graph.END = "__end__"
    fake_graph.StateGraph = _FakeStateGraph
    monkeypatch.setitem(sys.modules, "langgraph", fake_langgraph)
    monkeypatch.setitem(sys.modules, "langgraph.graph", fake_graph)

    registry = WorkflowToolRegistry()
    registry.register("root", lambda task_input, _dependencies: {"value": task_input["value"]})
    registry.register("join", lambda _input, dependencies: {"joined": dependencies["root"]["value"]})
    workflow = WorkflowDefinition(
        id="langgraph-runtime",
        tasks=[
            WorkflowTask(id="root", tool="root", input={"value": "ok"}),
            WorkflowTask(id="join", tool="join", dependencies=["root"]),
        ],
    )

    run = LangGraphWorkflowRuntime().execute(workflow, registry)

    assert run.status == "completed"
    assert run.outputs["join"] == {"joined": "ok"}
    assert [event.event for event in run.trace_events] == ["started", "completed", "started", "completed"]


def test_runtime_selector_prefers_langgraph_when_available(monkeypatch) -> None:
    fake_langgraph = ModuleType("langgraph")
    fake_graph = ModuleType("langgraph.graph")
    monkeypatch.setitem(sys.modules, "langgraph", fake_langgraph)
    monkeypatch.setitem(sys.modules, "langgraph.graph", fake_graph)

    selection = select_workflow_runtime()

    assert selection.name == "langgraph"
    assert isinstance(selection.runtime, LangGraphWorkflowRuntime)
    assert selection.warning is None


def test_runtime_selector_falls_back_to_native_when_langgraph_missing(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "langgraph", raising=False)
    monkeypatch.delitem(sys.modules, "langgraph.graph", raising=False)
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "langgraph.graph":
            raise ImportError("missing langgraph")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    selection = select_workflow_runtime()

    assert selection.name == "native"
    assert isinstance(selection.runtime, NativeWorkflowRuntime)
    assert selection.warning == "LangGraph is not installed; used native workflow runtime."


def test_executor_blocks_transitive_dependents_and_continues_independent_branch() -> None:
    registry = WorkflowToolRegistry()
    registry.register("fail", lambda _input, _dependencies: (_ for _ in ()).throw(RuntimeError("broken")))
    registry.register("identity", lambda task_input, _dependencies: task_input)
    registry.register("aggregate", lambda _input, dependencies: dependencies)
    workflow = WorkflowDefinition(
        id="failure",
        tasks=[
            WorkflowTask(id="failed_root", tool="fail"),
            WorkflowTask(id="blocked_child", tool="identity", dependencies=["failed_root"]),
            WorkflowTask(id="blocked_grandchild", tool="identity", dependencies=["blocked_child"]),
            WorkflowTask(id="independent", tool="identity", input={"ok": True}),
            WorkflowTask(id="independent_result", tool="aggregate", dependencies=["independent"]),
        ],
    )

    run = WorkflowExecutor(registry).execute(workflow)
    tasks = {task.id: task for task in run.tasks}

    assert run.status == "failed"
    assert tasks["failed_root"].status == "failed"
    assert tasks["blocked_child"].status == "blocked"
    assert tasks["blocked_grandchild"].status == "blocked"
    assert tasks["independent_result"].status == "completed"
    assert run.outputs["independent_result"] == {"independent": {"ok": True}}
    assert [event.event for event in run.trace_events if event.task_id == "failed_root"] == ["started", "failed"]
    assert [event.event for event in run.trace_events if event.task_id == "blocked_grandchild"] == ["blocked"]


def test_job_ingestion_template_includes_save_only_when_requested() -> None:
    request = SimpleNamespace(
        url="https://example.com/jobs/backend",
        save=True,
        use_browser_fallback=True,
        use_llm=False,
        use_llm_guidance=False,
    )

    save_workflow = build_job_ingestion_workflow(request)
    request.save = False
    preview_workflow = build_job_ingestion_workflow(request)

    assert [task.id for task in save_workflow.tasks] == ["fetch_job", "analyze_job", "save_job"]
    assert [task.id for task in preview_workflow.tasks] == ["fetch_job", "analyze_job"]


def test_prep_plan_workflow_template_exposes_agentic_branches() -> None:
    workflow = build_prep_plan_workflow(PrepPlanWorkflowRequest(timeline_days=7, hours_per_day=2, use_llm=False))

    assert [task.id for task in workflow.tasks] == [
        "plan_prep_workflow",
        "analyze_profile",
        "analyze_target_job",
        "analyze_coding_practice",
        "identify_skill_gaps",
        "generate_learning_plan",
        "generate_coding_plan",
        "generate_system_design_plan",
        "evaluate_prep_plan",
        "aggregate_plan",
    ]
    assert topological_groups(workflow.tasks) == [
        ["plan_prep_workflow"],
        ["analyze_coding_practice", "analyze_profile", "analyze_target_job"],
        ["identify_skill_gaps"],
        ["generate_coding_plan", "generate_learning_plan", "generate_system_design_plan"],
        ["evaluate_prep_plan"],
        ["aggregate_plan"],
    ]


def test_prep_plan_workflow_generates_traceable_plan() -> None:
    plan = PrepPlanWorkflowRunner(
        profile=ProfileStore().load_model(),
        jobs=[],
        coding_problems=[
            LeetCodeProblem(
                title="Two Sum",
                url="https://leetcode.com/problems/two-sum/",
                category="hash map",
                tags=["array"],
            )
        ],
        runtime=NativeWorkflowRuntime(),
    ).run(
        PrepPlanWorkflowRequest(
            timeline_days=3,
            hours_per_day=2,
            focus="Kubernetes, workflow orchestration",
            use_llm=False,
        )
    )

    assert plan.source == "workflow_generated"
    assert len(plan.days) == 3
    assert plan.workflow_graph is not None
    assert plan.workflow_graph["workflow_id"] == "prep_plan_generation"
    assert plan.workflow_run is not None
    assert plan.workflow_run["status"] == "completed"
    assert plan.workflow_run["runtime"]["name"] == "native"
    assert plan.workflow_run["runtime"]["warning"] is None
    assert plan.evaluation is not None
    assert plan.evaluation["status"] == "pass"


def test_prep_plan_workflow_can_run_through_langgraph_runtime(monkeypatch) -> None:
    fake_langgraph = ModuleType("langgraph")
    fake_graph = ModuleType("langgraph.graph")
    fake_graph.START = "__start__"
    fake_graph.END = "__end__"
    fake_graph.StateGraph = _FakeStateGraph
    monkeypatch.setitem(sys.modules, "langgraph", fake_langgraph)
    monkeypatch.setitem(sys.modules, "langgraph.graph", fake_graph)

    plan = PrepPlanWorkflowRunner(
        profile=ProfileStore().load_model(),
        jobs=[],
        coding_problems=[],
        runtime=LangGraphWorkflowRuntime(),
    ).run(
        PrepPlanWorkflowRequest(
            timeline_days=2,
            hours_per_day=1,
            focus="workflow orchestration",
            use_llm=False,
        )
    )

    assert plan.source == "workflow_generated"
    assert len(plan.days) == 2
    assert plan.workflow_run is not None
    assert plan.workflow_run["workflow_id"] == "prep_plan_generation"
    assert plan.workflow_run["status"] == "completed"
    assert plan.workflow_run["runtime"]["name"] == "langgraph"
    assert plan.workflow_run["runtime"]["warning"] is None


def test_prep_plan_default_runtime_falls_back_when_langgraph_execution_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.workflows.prep_plan.select_workflow_runtime",
        lambda: WorkflowRuntimeSelection(runtime=_UnavailableRuntime(), name="langgraph"),
    )

    plan = PrepPlanWorkflowRunner(
        profile=ProfileStore().load_model(),
        jobs=[],
        coding_problems=[],
    ).run(
        PrepPlanWorkflowRequest(
            timeline_days=1,
            hours_per_day=1,
            focus="workflow orchestration",
            use_llm=False,
        )
    )

    assert plan.workflow_run is not None
    assert plan.workflow_run["status"] == "completed"
    assert plan.workflow_run["runtime"]["name"] == "native"
    assert plan.workflow_run["runtime"]["warning"] == "LangGraph runtime failed to initialize."


def test_job_ingestion_runner_syncs_executor_trace_to_agent_task(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.agents.coordinator.score_job_fit_with_llm", _fake_job_fit)
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=repository,
    )
    task = repository.create_agent_task(
        task_type=AgentTaskType.JOB_LINK_INGEST,
        task_input={"url": "https://example.com/jobs/backend", "save": True},
        task_id="task-1",
    )
    request = SimpleNamespace(
        url="https://example.com/jobs/backend",
        save=True,
        use_browser_fallback=True,
        use_llm=False,
        use_llm_guidance=False,
    )

    JobIngestionWorkflowRunner(
        coordinator=coordinator,
        fetch_job_description=lambda _url, _browser: (_fake_fetched_page(), _fake_compacted_text()),
        fetch_summary=lambda url, compacted, source: f"Fetched {compacted.compacted_length} from {url} using {source}.",
    ).run(task.id, request)

    persisted = repository.get_agent_task(task.id)

    assert persisted is not None
    assert persisted.status == AgentTaskStatus.COMPLETED
    assert [step.name for step in persisted.steps] == ["fetch_job", "analyze_job", "save_job"]
    assert [step.status for step in persisted.steps] == ["completed", "completed", "completed"]
    assert persisted.artifacts["analysis"]["fit"]["score"] == 82
    assert persisted.artifacts["saved_job"]["id"] is not None
    assert persisted.artifacts["workflow_run"]["workflow_id"] == "job_ingestion"
    assert persisted.artifacts["workflow_graph"]["workflow_id"] == "job_ingestion"
    assert persisted.artifacts["workflow_graph"]["nodes"] == [
        {
            "id": "fetch_job",
            "label": "fetch job",
            "tool": "fetch_job",
            "description": "Fetch readable job text from the source link.",
            "status": "completed",
        },
        {
            "id": "analyze_job",
            "label": "analyze job",
            "tool": "analyze_job",
            "description": "Parse, score, and generate guidance.",
            "status": "completed",
        },
        {
            "id": "save_job",
            "label": "save job",
            "tool": "save_job",
            "description": "Persist reviewed analysis into the application tracker.",
            "status": "completed",
        },
    ]
    assert persisted.artifacts["workflow_graph"]["edges"] == [
        {"source": "fetch_job", "target": "analyze_job"},
        {"source": "fetch_job", "target": "save_job"},
        {"source": "analyze_job", "target": "save_job"},
    ]
    assert [event["event"] for event in persisted.artifacts["workflow_run"]["trace_events"]] == [
        "started",
        "completed",
        "started",
        "completed",
        "started",
        "completed",
    ]


def test_job_ingestion_runner_can_complete_preview_without_saving(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.agents.coordinator.score_job_fit_with_llm", _fake_job_fit)
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=repository,
    )
    task = repository.create_agent_task(
        task_type=AgentTaskType.JOB_LINK_INGEST,
        task_input={"url": "https://example.com/jobs/backend", "save": False},
        task_id="task-1",
    )
    request = SimpleNamespace(
        url="https://example.com/jobs/backend",
        save=False,
        use_browser_fallback=True,
        use_llm=False,
        use_llm_guidance=False,
    )

    JobIngestionWorkflowRunner(
        coordinator=coordinator,
        fetch_job_description=lambda _url, _browser: (_fake_fetched_page(), _fake_compacted_text()),
        fetch_summary=lambda url, compacted, source: f"Fetched {compacted.compacted_length} from {url} using {source}.",
    ).run(task.id, request)

    persisted = repository.get_agent_task(task.id)

    assert persisted is not None
    assert persisted.status == AgentTaskStatus.COMPLETED
    assert [step.name for step in persisted.steps] == ["fetch_job", "analyze_job"]
    assert persisted.artifacts["analysis"]["fit"]["score"] == 82
    assert "saved_job" not in persisted.artifacts
    assert repository.list_jobs() == []
    assert persisted.artifacts["workflow_graph"]["edges"] == [
        {"source": "fetch_job", "target": "analyze_job"},
    ]


def test_job_ingestion_runner_marks_task_failed_on_fetch_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.agents.coordinator.score_job_fit_with_llm", _fake_job_fit)
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    coordinator = JobSearchCoordinator(
        profile_store=ProfileStore(),
        repository=repository,
    )
    task = repository.create_agent_task(
        task_type=AgentTaskType.JOB_LINK_INGEST,
        task_input={"url": "https://example.com/jobs/backend", "save": True},
        task_id="task-1",
    )
    request = SimpleNamespace(
        url="https://example.com/jobs/backend",
        save=True,
        use_browser_fallback=True,
        use_llm=False,
        use_llm_guidance=False,
    )

    JobIngestionWorkflowRunner(
        coordinator=coordinator,
        fetch_job_description=lambda _url, _browser: (_ for _ in ()).throw(RuntimeError("fetch failed")),
        fetch_summary=lambda url, compacted, source: f"Fetched {compacted.compacted_length} from {url} using {source}.",
    ).run(task.id, request)

    persisted = repository.get_agent_task(task.id)

    assert persisted is not None
    assert persisted.status == AgentTaskStatus.FAILED
    assert [step.name for step in persisted.steps] == ["fetch_job", "analyze_job", "save_job"]
    assert persisted.steps[0].status == "failed"
    assert persisted.steps[1].status == "failed"
    assert persisted.steps[1].error == "Blocked by failed dependencies: fetch_job."
    assert persisted.error == "fetch failed"


def _fake_fetched_page():
    return SimpleNamespace(
        url="https://example.com/jobs/backend",
        title="Senior Backend Engineer",
        text="Senior Backend Engineer",
        extraction_source="test",
        extraction_recipe=None,
        extraction_strategy=None,
        extracted_posting=None,
    )


def _fake_compacted_text():
    return SimpleNamespace(
        text="""
        Senior Backend Engineer, AI Platform
        Company: Example AI
        Build Python backend services for distributed agent workflow infrastructure.
        """,
        compacted_length=140,
        original_length=140,
        was_compacted=False,
    )


def _fake_job_fit(profile: dict, job) -> JobFit:
    del profile, job
    return JobFit(
        score=82,
        priority="high",
        strong_matches=["Python"],
        gaps=[],
        concerns=[],
        summary="Strong test fit.",
        recommendation="apply",
    )
