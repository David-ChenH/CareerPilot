import json
import os
from typing import Any

from app.config.env import load_local_env
from app.db.models import JobChatMessage, JobDetail


DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_WEB_SEARCH_MODEL = "gpt-5.4-mini"


class LLMJobChatUnavailable(RuntimeError):
    pass


class JobChatAnswer:
    def __init__(self, answer: str, citations: list[dict[str, str]] | None = None) -> None:
        self.answer = answer
        self.citations = citations or []


def answer_job_chat_with_llm(
    profile: dict[str, Any],
    detail: JobDetail,
    messages: list[JobChatMessage],
    use_web_search: bool = False,
) -> JobChatAnswer:
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMJobChatUnavailable("OPENAI_API_KEY is not set.")

    try:
        from openai import OpenAI
    except ImportError as error:
        raise LLMJobChatUnavailable(
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
                    "You are a job-search and interview-prep assistant inside a local-first job analysis app. "
                    "Answer follow-up questions using only the supplied user profile, saved job, saved analysis, "
                    "chat history, and web results only when the web search tool is enabled. Be concrete, practical, "
                    "and honest. Do not invent experience or claim the user has skills that are not in the profile. "
                    "If the user asks for resume wording, keep it truthful and frame existing experience toward the role. "
                    "If web search is enabled, cite sources for current company, product, interview, or market claims. "
                    "If web search is not enabled, avoid making claims that require current external information. "
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
                        "job": detail.job.model_dump(),
                        "analysis": detail.analysis,
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
        raise LLMJobChatUnavailable("LLM chat returned no text output.")
    return JobChatAnswer(answer=answer, citations=_extract_citations(response))


def _extract_citations(response: Any) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    for item in getattr(response, "output", []) or []:
        item_type = _read_value(item, "type")
        if item_type == "message":
            for content in _read_value(item, "content") or []:
                for annotation in _read_value(content, "annotations") or []:
                    if _read_value(annotation, "type") == "url_citation":
                        _append_citation(
                            citations,
                            url=_read_value(annotation, "url"),
                            title=_read_value(annotation, "title"),
                        )
        if item_type == "web_search_call":
            action = _read_value(item, "action") or {}
            for source in _read_value(action, "sources") or []:
                _append_citation(
                    citations,
                    url=_read_value(source, "url"),
                    title=_read_value(source, "title"),
                )
    return citations


def _append_citation(citations: list[dict[str, str]], url: str | None, title: str | None) -> None:
    if not url:
        return
    if any(citation["url"] == url for citation in citations):
        return
    citations.append({"url": url, "title": title or url})


def _read_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)
