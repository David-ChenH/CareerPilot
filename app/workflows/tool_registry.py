from collections.abc import Callable
from typing import Any


WorkflowTool = Callable[[dict, dict[str, Any]], Any]


class WorkflowToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, WorkflowTool] = {}

    def register(self, name: str, tool: WorkflowTool) -> None:
        if not name.strip():
            raise ValueError("Workflow tool name must not be empty.")
        self._tools[name] = tool

    def get(self, name: str) -> WorkflowTool:
        try:
            return self._tools[name]
        except KeyError as error:
            raise KeyError(f"Workflow tool {name!r} is not registered.") from error

    def contains(self, name: str) -> bool:
        return name in self._tools
