from collections.abc import Callable
from dataclasses import dataclass

from app.agents.assistant_planner import (
    ActionExecutionResult,
    ActionExecutionStatus,
    AssistantPlannedAction,
)


ApprovalPolicy = Callable[[AssistantPlannedAction], bool]


@dataclass(frozen=True)
class ActionMetadata:
    name: str
    description: str
    required_arguments: tuple[str, ...] = ()
    requires_approval: ApprovalPolicy = lambda _action: False


class ActionRegistry:
    """Allow-list and validation boundary for assistant-planned actions."""

    def __init__(self) -> None:
        self._actions = {
            "ingest_job_from_url": ActionMetadata(
                name="ingest_job_from_url",
                description="Fetch a job link, analyze it, and optionally save it to the application tracker.",
                required_arguments=("url", "save"),
                requires_approval=lambda action: bool(action.arguments.save),
            ),
            "update_profile_memory": ActionMetadata(
                name="update_profile_memory",
                description="Apply reviewed profile-memory updates.",
                required_arguments=("proposed_updates",),
                requires_approval=lambda _action: True,
            ),
            "generate_prep_plan": ActionMetadata(
                name="generate_prep_plan",
                description="Generate and save an interview preparation plan.",
                requires_approval=lambda _action: True,
            ),
            "generate_resume": ActionMetadata(
                name="generate_resume",
                description="Generate and save a targeted resume version.",
                required_arguments=("resume_target",),
                requires_approval=lambda _action: True,
            ),
            "compare_saved_jobs": ActionMetadata(
                name="compare_saved_jobs",
                description="Compare saved jobs and rank them for the user's current goals.",
            ),
        }

    def is_allowed(self, action_name: str) -> bool:
        return action_name in self._actions

    def metadata(self, action_name: str) -> ActionMetadata | None:
        return self._actions.get(action_name)

    def validate_planned_action(self, action: AssistantPlannedAction) -> ActionExecutionResult | None:
        metadata = self.metadata(action.name)
        if metadata is None:
            return ActionExecutionResult(
                action_name=action.name,
                status=ActionExecutionStatus.REJECTED,
                summary=f"Rejected unknown assistant action: {action.name}.",
            )

        missing = [
            argument
            for argument in metadata.required_arguments
            if _is_missing_argument(action, argument)
        ]
        if missing:
            return ActionExecutionResult(
                action_name=action.name,
                status=ActionExecutionStatus.REJECTED,
                summary=f"Rejected {action.name}: missing required argument(s): {', '.join(missing)}.",
            )

        if metadata.requires_approval(action) and not action.approval_confirmed:
            return ActionExecutionResult(
                action_name=action.name,
                status=ActionExecutionStatus.NEEDS_CONFIRMATION,
                summary=f"{action.name} needs confirmation before CareerPilot changes local data.",
                details={"arguments": action.arguments.model_dump(mode="json")},
            )

        return None


def _is_missing_argument(action: AssistantPlannedAction, argument: str) -> bool:
    if argument == "url":
        return not (action.arguments.url or "").strip()
    if argument == "save":
        return action.arguments.save is None
    if argument == "proposed_updates":
        return not action.arguments.proposed_updates.to_updates()
    if argument == "resume_target":
        return not (action.arguments.role_title or "").strip() and action.arguments.job_id is None
    return True
