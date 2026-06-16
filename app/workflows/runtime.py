from collections.abc import Callable
from typing import Any, Protocol, TypedDict
from uuid import uuid4

from app.workflows.dag import topological_groups, validate_workflow
from app.workflows.executor import WorkflowExecutionError, WorkflowExecutor
from app.workflows.models import WorkflowDefinition, WorkflowRun, WorkflowRunStatus, WorkflowTaskStatus
from app.workflows.tool_registry import WorkflowToolRegistry
from app.workflows.trace import WorkflowTraceEvent, trace_event


class WorkflowRuntime(Protocol):
    def execute(
        self,
        workflow: WorkflowDefinition,
        registry: WorkflowToolRegistry,
        on_event: Callable[[WorkflowTraceEvent, WorkflowRun, Any, Any | None], None] | None = None,
    ) -> WorkflowRun:
        ...


class NativeWorkflowRuntime:
    """Current in-process CareerPilot runtime used as the learning baseline."""

    def execute(
        self,
        workflow: WorkflowDefinition,
        registry: WorkflowToolRegistry,
        on_event: Callable[[WorkflowTraceEvent, WorkflowRun, Any, Any | None], None] | None = None,
    ) -> WorkflowRun:
        return WorkflowExecutor(registry).execute(workflow, on_event=on_event)


class LangGraphRuntimeUnavailable(RuntimeError):
    pass


class _WorkflowState(TypedDict):
    run: WorkflowRun


class LangGraphWorkflowRuntime:
    """LangGraph-backed runtime for approved CareerPilot workflow templates.

    This first adapter preserves current execution semantics by running each
    dependency-ready group as a graph node. That keeps the comparison clean:
    the domain workflow, tools, trace events, and final artifacts stay the same
    while scheduling can move behind LangGraph.
    """

    def execute(
        self,
        workflow: WorkflowDefinition,
        registry: WorkflowToolRegistry,
        on_event: Callable[[WorkflowTraceEvent, WorkflowRun, Any, Any | None], None] | None = None,
    ) -> WorkflowRun:
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError as error:
            raise LangGraphRuntimeUnavailable(
                'LangGraph is not installed. Install it with `pip install -e ".[dev,ai]"`.'
            ) from error

        validate_workflow(workflow)
        _validate_tools(workflow, registry)
        run = _new_run(workflow)
        groups = topological_groups(run.tasks)
        graph = StateGraph(_WorkflowState)

        previous_node = START
        for index, group in enumerate(groups):
            node_name = f"group_{index + 1}"
            graph.add_node(node_name, _group_runner(group, registry, on_event))
            graph.add_edge(previous_node, node_name)
            previous_node = node_name
        graph.add_edge(previous_node, END)

        final_state = graph.compile().invoke({"run": run})
        final_run = final_state["run"]
        final_run.status = (
            WorkflowRunStatus.FAILED
            if any(task.status == WorkflowTaskStatus.FAILED for task in final_run.tasks)
            else WorkflowRunStatus.COMPLETED
        )
        return final_run


def _group_runner(
    ready_group: list[str],
    registry: WorkflowToolRegistry,
    on_event: Callable[[WorkflowTraceEvent, WorkflowRun, Any, Any | None], None] | None,
):
    def run_group(state: _WorkflowState) -> _WorkflowState:
        run = state["run"]
        by_id = {task.id: task for task in run.tasks}
        for task_id in ready_group:
            task = by_id[task_id]
            blocked_by = [
                dependency
                for dependency in task.dependencies
                if by_id[dependency].status in {WorkflowTaskStatus.FAILED, WorkflowTaskStatus.BLOCKED}
            ]
            if blocked_by:
                task.status = WorkflowTaskStatus.BLOCKED
                task.error_type = "dependency_failed"
                _emit(
                    run,
                    trace_event(task.id, "blocked", f"Blocked by failed dependencies: {', '.join(blocked_by)}."),
                    task,
                    on_event,
                )
                continue

            dependency_outputs = {dependency: run.outputs[dependency] for dependency in task.dependencies}
            task.status = WorkflowTaskStatus.RUNNING
            _emit(run, trace_event(task.id, "started"), task, on_event)
            try:
                output = registry.get(task.tool)(task.input, dependency_outputs)
            except Exception as error:
                task.status = WorkflowTaskStatus.FAILED
                task.error_type = type(error).__name__
                _emit(run, trace_event(task.id, "failed", str(error) or type(error).__name__), task, on_event)
                continue

            run.outputs[task.id] = output
            task.status = WorkflowTaskStatus.COMPLETED
            _emit(run, trace_event(task.id, "completed"), task, on_event, output)
        return {"run": run}

    return run_group


def _new_run(workflow: WorkflowDefinition) -> WorkflowRun:
    return WorkflowRun(
        id=str(uuid4()),
        workflow_id=workflow.id,
        workflow_version=workflow.version,
        status=WorkflowRunStatus.RUNNING,
        tasks=[task.model_copy(deep=True) for task in workflow.tasks],
    )


def _validate_tools(workflow: WorkflowDefinition, registry: WorkflowToolRegistry) -> None:
    unknown_tools = sorted({task.tool for task in workflow.tasks if not registry.contains(task.tool)})
    if unknown_tools:
        raise WorkflowExecutionError(f"Workflow uses unregistered tools: {', '.join(unknown_tools)}.")


def _emit(
    run: WorkflowRun,
    event: WorkflowTraceEvent,
    task,
    on_event: Callable[[WorkflowTraceEvent, WorkflowRun, Any, Any | None], None] | None,
    output: Any | None = None,
) -> None:
    run.trace_events.append(event)
    if on_event:
        on_event(event, run, task, output)
