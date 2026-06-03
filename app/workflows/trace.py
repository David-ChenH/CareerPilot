from datetime import datetime, timezone

from pydantic import BaseModel


class WorkflowTraceEvent(BaseModel):
    task_id: str
    event: str
    timestamp: str
    detail: str | None = None


def trace_event(task_id: str, event: str, detail: str | None = None) -> WorkflowTraceEvent:
    return WorkflowTraceEvent(
        task_id=task_id,
        event=event,
        timestamp=datetime.now(timezone.utc).isoformat(),
        detail=detail,
    )
