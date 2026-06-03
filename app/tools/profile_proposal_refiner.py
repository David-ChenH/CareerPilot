import json
import os
import re
from typing import Any

from pydantic import BaseModel, Field

from app.config.env import load_local_env
from app.tools.llm_job_chat import DEFAULT_LLM_MODEL


class ProfileProposalRefinement(BaseModel):
    answer: str = Field(description="Short assistant response explaining the proposed change.")
    proposed_updates: dict[str, list[str]] = Field(description="Updated profile proposal grouped by profile field.")


class ProfileProposalRefinerUnavailable(RuntimeError):
    pass


def refine_profile_proposal_with_llm(
    profile: dict[str, Any],
    proposed_updates: dict[str, list[str]],
    message: str,
) -> ProfileProposalRefinement:
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ProfileProposalRefinerUnavailable("OPENAI_API_KEY is not set.")

    try:
        from openai import OpenAI
    except ImportError as error:
        raise ProfileProposalRefinerUnavailable(
            'OpenAI SDK is not installed. Install it with `pip install -e ".[dev,ai]"`.'
        ) from error

    client = OpenAI(api_key=api_key)
    model = os.getenv("JOB_AGENT_LLM_MODEL", DEFAULT_LLM_MODEL)
    response = client.responses.parse(
        model=model,
        input=[
            {
                "role": "system",
                "content": (
                    "You refine proposed local profile-memory updates for a career assistant. "
                    "Do not write memory. Return only a revised proposal and a concise explanation. "
                    "Keep claims truthful and grounded in the current profile, proposal, and user instruction. "
                    "If the user asks to remove, soften, reclassify, or add a fact, update the proposal accordingly. "
                    "Use top-level profile fields such as technical_strengths, experience_highlights, target_roles, "
                    "career_goals, learning_goals, must_have, nice_to_have, avoid, and unknown_or_to_confirm."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "current_profile": profile,
                        "current_proposal": proposed_updates,
                        "user_instruction": message,
                    },
                    ensure_ascii=True,
                ),
            },
        ],
        text_format=ProfileProposalRefinement,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise ProfileProposalRefinerUnavailable("Profile proposal refiner returned no structured output.")
    return parsed


def refine_profile_proposal_deterministically(
    proposed_updates: dict[str, list[str]],
    message: str,
) -> ProfileProposalRefinement:
    updated = {key: [*values] for key, values in proposed_updates.items()}
    lowered = message.lower()

    remove_match = re.search(r"\b(?:remove|delete|drop)\s+(.+?)(?:\s+from\s+([\w_ -]+))?$", message, flags=re.IGNORECASE)
    add_match = re.search(r"\badd\s+(.+?)\s+to\s+([\w_ -]+)$", message, flags=re.IGNORECASE)

    if remove_match:
        term = remove_match.group(1).strip().strip("\"'")
        field = _normalize_field(remove_match.group(2)) if remove_match.group(2) else None
        target_fields = [field] if field else list(updated.keys())
        for key in target_fields:
            if key in updated:
                updated[key] = [value for value in updated[key] if term.lower() not in value.lower()]
        return ProfileProposalRefinement(
            answer=f"Removed proposal items matching `{term}`. Review the updated proposal before saving.",
            proposed_updates=_drop_empty(updated),
        )

    if add_match:
        value = add_match.group(1).strip().strip("\"'")
        field = _normalize_field(add_match.group(2))
        updated.setdefault(field, [])
        if value and value.lower() not in {item.lower() for item in updated[field]}:
            updated[field].append(value)
        return ProfileProposalRefinement(
            answer=f"Added `{value}` to `{field}` in the proposal. Review before saving.",
            proposed_updates=_drop_empty(updated),
        )

    if "what" in lowered or "why" in lowered or "explain" in lowered:
        count = sum(len(values) for values in updated.values())
        return ProfileProposalRefinement(
            answer=(
                f"The current proposal has {count} profile facts. Save only facts you are comfortable using for future "
                "job matching, resume guidance, and assistant answers. You can ask me to add or remove a specific item."
            ),
            proposed_updates=_drop_empty(updated),
        )

    return ProfileProposalRefinement(
        answer=(
            "I kept the proposal unchanged. In local fallback mode I can handle instructions like "
            "`add Java to technical_strengths` or `remove Kubernetes`."
        ),
        proposed_updates=_drop_empty(updated),
    )


def _normalize_field(value: str | None) -> str:
    return (value or "technical_strengths").strip().lower().replace(" ", "_").replace("-", "_")


def _drop_empty(updates: dict[str, list[str]]) -> dict[str, list[str]]:
    return {key: values for key, values in updates.items() if values}
