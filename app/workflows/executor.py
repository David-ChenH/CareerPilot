from collections.abc import Callable
from typing import Any
from uuid import uuid4

from app.workflows.dag import topological_groups, validate_workflow
from app.workflows.models import WorkflowDefinition, WorkflowRun, WorkflowRunStatus, WorkflowTaskStatus
from app.workflows.tool_registry import WorkflowToolRegistry
from app.workflows.trace import WorkflowTraceEvent, trace_event


class WorkflowExecutionError(RuntimeError):
    pass


class WorkflowExecutor:
    def __init__(self, registry: WorkflowToolRegistry) -> None:
        self.registry = registry

    def execute(
        self,
        workflow: WorkflowDefinition,
        on_event: Callable[[WorkflowTraceEvent, WorkflowRun, Any, Any | None], None] | None = None,
    ) -> WorkflowRun:
        validate_workflow(workflow)
        self._validate_tools(workflow)
        run = WorkflowRun(
            id=str(uuid4()),
            workflow_id=workflow.id,
            workflow_version=workflow.version,
            status=WorkflowRunStatus.RUNNING,
            tasks=[task.model_copy(deep=True) for task in workflow.tasks],
        )
        by_id = {task.id: task for task in run.tasks}

        for ready_group in topological_groups(run.tasks):
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
                    self._emit(
                        run,
                        trace_event(task.id, "blocked", f"Blocked by failed dependencies: {', '.join(blocked_by)}."),
                        task,
                        on_event,
                    )
                    continue

                dependency_outputs = {dependency: run.outputs[dependency] for dependency in task.dependencies}
                task.status = WorkflowTaskStatus.RUNNING
                self._emit(run, trace_event(task.id, "started"), task, on_event)
                try:
                    output = self.registry.get(task.tool)(task.input, dependency_outputs)
                except Exception as error:
                    task.status = WorkflowTaskStatus.FAILED
                    task.error_type = type(error).__name__
                    self._emit(
                        run,
                        trace_event(task.id, "failed", str(error) or type(error).__name__),
                        task,
                        on_event,
                    )
                    continue

                run.outputs[task.id] = output
                task.status = WorkflowTaskStatus.COMPLETED
                self._emit(run, trace_event(task.id, "completed"), task, on_event, output)

        run.status = (
            WorkflowRunStatus.FAILED
            if any(task.status == WorkflowTaskStatus.FAILED for task in run.tasks)
            else WorkflowRunStatus.COMPLETED
        )
        return run

    def _validate_tools(self, workflow: WorkflowDefinition) -> None:
        unknown_tools = sorted({task.tool for task in workflow.tasks if not self.registry.contains(task.tool)})
        if unknown_tools:
            raise WorkflowExecutionError(f"Workflow uses unregistered tools: {', '.join(unknown_tools)}.")

    def _emit(
        self,
        run: WorkflowRun,
        event: WorkflowTraceEvent,
        task,
        on_event: Callable[[WorkflowTraceEvent, WorkflowRun, Any, Any | None], None] | None,
        output: Any | None = None,
    ) -> None:
        run.trace_events.append(event)
        if on_event:
            on_event(event, run, task, output)
