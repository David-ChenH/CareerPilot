import json
import os
from typing import Any

from app.config.env import load_local_env
from app.db.models import GlobalChatMessage, JobRecord
from app.tools.llm_job_chat import DEFAULT_LLM_MODEL, DEFAULT_WEB_SEARCH_MODEL, JobChatAnswer, _extract_citations


class LLMGlobalChatUnavailable(RuntimeError):
    pass


def answer_global_chat_with_llm(
    profile: dict[str, Any],
    jobs: list[JobRecord],
    messages: list[GlobalChatMessage],
    use_web_search: bool = False,
) -> JobChatAnswer:
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMGlobalChatUnavailable("OPENAI_API_KEY is not set.")

    try:
        from openai import OpenAI
    except ImportError as error:
        raise LLMGlobalChatUnavailable(
            'OpenAI SDK is not installed. Install it with `pip install -e ".[dev,ai]"`.'
        ) from error

    client = OpenAI(api_key=api_key)
    model = os.getenv(
        "JOB_AGENT_WEB_SEARCH_MODEL" if use_web_search else "JOB_AGENT_LLM_MODEL",
        DEFAULT_WEB_SEARCH_MODEL if use_web_search else DEFAULT_LLM_MODEL,
    )
    tools = [{"type": "web_search"}] if use_web_search else None

    request: dict[str, Any] = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are the global assistant for a local-first job-search workbench. "
                    "Help the user plan their job search, compare saved jobs, identify repeated gaps, "
                    "prioritize learning, and decide next actions. Use the supplied local profile, saved job "
                    "summaries, application statuses, and chat history. Do not invent user experience. "
                    "If the user asks to update, correct, add, or remember profile facts, do not turn that into "
                    "a job-search plan; acknowledge that profile memory updates should use the app's explicit "
                    "memory update path. For resume or profile claims, stay truthful. "
                    "Use web results only when the web search tool is enabled, and cite sources for current external claims. "
                    "Answer the latest user message directly; use earlier chat only as context and do not repeat a prior answer "
                    "unless the user asks you to restate it."
                ),
            },
            {
                "role": "system",
                "content": "Local context JSON: "
                + json.dumps(
                    {
                        "profile": profile,
                        "saved_jobs": [_summarize_job(job) for job in jobs[:30]],
                    },
                    ensure_ascii=True,
                ),
            },
            *[
                {
                    "role": message.role.value,
                    "content": message.content,
                }
                for message in messages[-12:]
            ],
        ],
    }
    if tools:
        request["tools"] = tools
        request["tool_choice"] = "auto"
        request["include"] = ["web_search_call.action.sources"]

    response = client.responses.create(**request)
    answer = getattr(response, "output_text", "").strip()
    if not answer:
        raise LLMGlobalChatUnavailable("LLM global chat returned no text output.")
    return JobChatAnswer(answer=answer, citations=_extract_citations(response))


def _summarize_job(job: JobRecord) -> dict[str, Any]:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "source_url": job.source_url,
        "skills": job.skills,
        "fit_score": job.fit_score,
        "priority": job.priority,
        "status": job.status.value,
        "analysis_summary": (job.analysis or {}).get("fit", {}).get("summary"),
        "gaps": (job.analysis or {}).get("fit", {}).get("gaps", []),
        "prep_plan": (job.analysis or {}).get("guidance", {}).get("prep_plan", [])[:5],
    }
