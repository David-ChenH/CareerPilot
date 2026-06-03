import re
from dataclasses import dataclass, field
from typing import Any


URL_PATTERN = re.compile(r"https?://[^\s<>\]\)\"']+")
JOB_ACTION_TERMS = {
    "analyze",
    "analyse",
    "save",
    "track",
    "ingest",
    "fetch",
    "job",
    "role",
    "position",
    "application",
    "apply",
}


@dataclass(frozen=True)
class AgentAction:
    name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    summary: str = ""


class ActionRegistry:
    """Small allow-list of application actions the assistant may request."""

    def __init__(self) -> None:
        self._actions = {"ingest_job_from_url"}

    def is_allowed(self, action_name: str) -> bool:
        return action_name in self._actions

    def detect_from_message(self, message: str) -> AgentAction | None:
        clean_message = message.strip()
        url = _extract_first_url(clean_message)
        if not url:
            return None

        normalized = clean_message.lower()
        if not any(term in normalized for term in JOB_ACTION_TERMS):
            return None

        requested_save = any(term in normalized for term in ["save", "track", "application", "apply"])
        return AgentAction(
            name="ingest_job_from_url",
            parameters={"url": url, "save": requested_save},
            summary="Detected a job URL and routed it into the job ingestion workflow.",
        )


def _extract_first_url(message: str) -> str | None:
    match = URL_PATTERN.search(message)
    if not match:
        return None
    return match.group(0).rstrip(".,;:")
