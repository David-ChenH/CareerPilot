import json
import os
from typing import Any

from app.artifacts import (
    PREP_PLAN_PROMPT_VERSION,
    PREP_PLAN_WORKFLOW_VERSION,
    artifact_provenance,
    configured_llm_model,
)
from app.config.env import load_local_env
from app.db.models import JobRecord, PrepDay, PrepPlan, PrepTask
from app.tools.llm_job_chat import DEFAULT_LLM_MODEL


DEFAULT_TOPICS = [
    ("Kubernetes fundamentals", "learning"),
    ("Docker and container workflow", "learning"),
    ("Distributed systems review", "system_design"),
    ("Backend system design practice", "system_design"),
    ("LeetCode medium practice", "leetcode"),
    ("Behavioral story rehearsal", "interview"),
]


class LLMPrepPlannerUnavailable(RuntimeError):
    pass


def generate_prep_plan_with_llm(
    profile: dict[str, Any],
    jobs: list[JobRecord],
    timeline_days: int,
    hours_per_day: float,
    focus: str | None = None,
    job_id: int | None = None,
) -> PrepPlan:
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMPrepPlannerUnavailable("OPENAI_API_KEY is not set.")

    try:
        from openai import OpenAI
    except ImportError as error:
        raise LLMPrepPlannerUnavailable(
            'OpenAI SDK is not installed. Install it with `pip install -e ".[dev,ai]"`.'
        ) from error

    timeline = max(1, min(timeline_days, 90))
    hours = max(0.5, min(hours_per_day, 12))
    selected_job = next((job for job in jobs if job.id == job_id), None)
    client = OpenAI(api_key=api_key)
    response = client.responses.parse(
        model=configured_llm_model(DEFAULT_LLM_MODEL),
        input=[
            {
                "role": "system",
                "content": (
                    "Generate a practical interview preparation plan for a backend/software engineer. "
                    "Return structured daily checklist data only. Each day should include learning, LeetCode, "
                    "system design or interview practice when appropriate. Fit task minutes within the user's "
                    "available hours per day. Make the plan specific to the profile, target job, and focus areas."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "profile": profile,
                        "target_job": selected_job.model_dump() if selected_job else None,
                        "saved_jobs_summary": [
                            {
                                "title": job.title,
                                "company": job.company,
                                "skills": job.skills,
                                "gaps": (job.analysis or {}).get("fit", {}).get("gaps", []),
                            }
                            for job in jobs[:10]
                        ],
                        "timeline_days": timeline,
                        "hours_per_day": hours,
                        "focus": focus,
                    },
                    ensure_ascii=True,
                ),
            },
        ],
        text_format=PrepPlan,
    )
    plan = response.output_parsed
    if plan is None:
        raise LLMPrepPlannerUnavailable("LLM prep planner returned no structured output.")
    plan.id = None
    plan.source = "llm"
    plan.provenance = artifact_provenance(
        generator="llm",
        workflow_version=PREP_PLAN_WORKFLOW_VERSION,
        schema_version=plan.schema_version,
        prompt_version=PREP_PLAN_PROMPT_VERSION,
        model=configured_llm_model(DEFAULT_LLM_MODEL),
    )
    plan.timeline_days = timeline
    plan.hours_per_day = hours
    return plan


def generate_prep_plan(
    profile: dict[str, Any],
    jobs: list[JobRecord],
    timeline_days: int,
    hours_per_day: float,
    focus: str | None = None,
    job_id: int | None = None,
) -> PrepPlan:
    timeline = max(1, min(timeline_days, 90))
    hours = max(0.5, min(hours_per_day, 12))
    selected_job = next((job for job in jobs if job.id == job_id), None)
    topics = _topics_from_context(profile, selected_job, focus)
    minutes_per_day = int(hours * 60)
    days = []
    for index in range(timeline):
        topic, category = topics[index % len(topics)]
        tasks = [
            PrepTask(title=f"Study: {topic}", category=category, minutes=max(25, minutes_per_day // 2)),
            PrepTask(title="LeetCode practice: 1 focused problem", category="leetcode", minutes=max(25, minutes_per_day // 4)),
            PrepTask(title="Write notes and interview takeaways", category="review", minutes=max(15, minutes_per_day // 4)),
        ]
        if index % 3 == 2:
            tasks.append(PrepTask(title="Mock system design outline", category="system_design", minutes=45))
        days.append(PrepDay(day=index + 1, title=f"Day {index + 1}: {topic}", tasks=tasks))

    target = selected_job.title if selected_job else "career transition"
    return PrepPlan(
        title=f"{timeline}-day prep plan for {target}",
        source="generated",
        timeline_days=timeline,
        hours_per_day=hours,
        days=days,
        provenance=artifact_provenance(
            generator="deterministic",
            workflow_version=PREP_PLAN_WORKFLOW_VERSION,
            schema_version=1,
        ),
    )


def parse_prep_plan_text(text: str, title: str = "Imported prep plan") -> PrepPlan:
    lines = [line.strip(" -*\t") for line in text.splitlines() if line.strip(" -*\t")]
    days: list[PrepDay] = []
    current_tasks: list[PrepTask] = []
    day_number = 1
    for line in lines:
        lowered = line.lower()
        if lowered.startswith("day ") and current_tasks:
            days.append(PrepDay(day=day_number, title=f"Day {day_number}", tasks=current_tasks))
            day_number += 1
            current_tasks = []
        elif not lowered.startswith("day "):
            current_tasks.append(PrepTask(title=line, category=_guess_category(line), minutes=45))
    if current_tasks:
        days.append(PrepDay(day=day_number, title=f"Day {day_number}", tasks=current_tasks))
    if not days:
        days = [PrepDay(day=1, title="Day 1", tasks=[PrepTask(title="Review imported plan text", category="review")])]
    return PrepPlan(
        title=title.strip() or "Imported prep plan",
        source="imported",
        timeline_days=len(days),
        hours_per_day=2,
        days=days,
        provenance=artifact_provenance(
            generator="imported",
            workflow_version=PREP_PLAN_WORKFLOW_VERSION,
            schema_version=1,
        ),
    )


def _topics_from_context(profile: dict[str, Any], job: JobRecord | None, focus: str | None) -> list[tuple[str, str]]:
    topics = []
    if focus:
        topics.extend((item.strip(), "learning") for item in focus.split(",") if item.strip())
    if job and job.analysis:
        fit = job.analysis.get("fit", {})
        guidance = job.analysis.get("guidance", {})
        topics.extend((gap, "learning") for gap in fit.get("gaps", [])[:5])
        topics.extend((item, "interview") for item in guidance.get("interview_focus", [])[:3])
        topics.extend((skill, "learning") for skill in job.skills[:5])
    topics.extend((goal, "learning") for goal in profile.get("learning_goals", [])[:5])
    topics.extend(DEFAULT_TOPICS)
    return _dedupe_topics(topics)


def _dedupe_topics(values: list[tuple[str, str]]) -> list[tuple[str, str]]:
    result = []
    seen = set()
    for title, category in values:
        key = title.lower()
        if key not in seen:
            seen.add(key)
            result.append((title, category))
    return result


def _guess_category(value: str) -> str:
    lowered = value.lower()
    if "leetcode" in lowered or "algorithm" in lowered:
        return "leetcode"
    if "system design" in lowered or "design" in lowered:
        return "system_design"
    if "mock" in lowered or "interview" in lowered:
        return "interview"
    return "learning"
