from app.workflows.models import (
    WorkflowDefinition,
    WorkflowGraph,
    WorkflowGraphEdge,
    WorkflowGraphNode,
    WorkflowRun,
    WorkflowTask,
)


def workflow_graph_from_definition(workflow: WorkflowDefinition) -> WorkflowGraph:
    """Serialize the planned workflow shape for API/UI consumers.

    This is intentionally separate from execution trace data. The graph answers
    "what can run and what depends on what"; trace events answer "what happened
    during this specific run."
    """
    return _workflow_graph(
        workflow_id=workflow.id,
        workflow_version=workflow.version,
        tasks=workflow.tasks,
    )


def workflow_graph_from_run(run: WorkflowRun) -> WorkflowGraph:
    """Serialize the executed workflow shape with final task statuses."""
    return _workflow_graph(
        workflow_id=run.workflow_id,
        workflow_version=run.workflow_version,
        tasks=run.tasks,
    )


def _workflow_graph(*, workflow_id: str, workflow_version: int, tasks: list[WorkflowTask]) -> WorkflowGraph:
    return WorkflowGraph(
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        nodes=[
            WorkflowGraphNode(
                id=task.id,
                label=task.id.replace("_", " "),
                tool=task.tool,
                description=task.description,
                status=task.status,
            )
            for task in tasks
        ],
        edges=[
            WorkflowGraphEdge(source=dependency, target=task.id)
            for task in tasks
            for dependency in task.dependencies
        ],
    )
