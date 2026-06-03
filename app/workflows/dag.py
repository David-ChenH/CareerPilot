from app.workflows.models import WorkflowDefinition, WorkflowTask


class WorkflowGraphError(ValueError):
    pass


def validate_workflow(workflow: WorkflowDefinition) -> None:
    task_ids = [task.id for task in workflow.tasks]
    duplicates = sorted(task_id for task_id in set(task_ids) if task_ids.count(task_id) > 1)
    if duplicates:
        raise WorkflowGraphError(f"Workflow contains duplicate task IDs: {', '.join(duplicates)}.")

    known_ids = set(task_ids)
    for task in workflow.tasks:
        missing = sorted(set(task.dependencies) - known_ids)
        if missing:
            raise WorkflowGraphError(
                f"Task {task.id!r} depends on unknown tasks: {', '.join(missing)}."
            )

    topological_groups(workflow.tasks, validate_dependencies=False)


def topological_order(workflow: WorkflowDefinition) -> list[str]:
    return [task_id for group in topological_groups(workflow.tasks) for task_id in group]


def topological_groups(
    tasks: list[WorkflowTask],
    *,
    validate_dependencies: bool = True,
) -> list[list[str]]:
    by_id = {task.id: task for task in tasks}
    if len(by_id) != len(tasks):
        raise WorkflowGraphError("Workflow contains duplicate task IDs.")

    indegree = {task.id: 0 for task in tasks}
    dependents = {task.id: [] for task in tasks}
    for task in tasks:
        for dependency in task.dependencies:
            if dependency not in by_id:
                if validate_dependencies:
                    raise WorkflowGraphError(f"Task {task.id!r} depends on unknown task {dependency!r}.")
                continue
            indegree[task.id] += 1
            dependents[dependency].append(task.id)

    groups = []
    ready = sorted(task_id for task_id, degree in indegree.items() if degree == 0)
    while ready:
        groups.append(ready)
        next_ready = []
        for task_id in ready:
            for dependent in dependents[task_id]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    next_ready.append(dependent)
        ready = sorted(next_ready)

    if sum(len(group) for group in groups) != len(tasks):
        raise WorkflowGraphError("Workflow contains a dependency cycle.")
    return groups
