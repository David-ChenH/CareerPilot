import json
import os

from pydantic import BaseModel, Field

from app.config.env import load_local_env
from app.tools.content_root_strategy import ContentRootSemanticValidation, ContentRootStrategy
from app.tools.llm_job_parser import DEFAULT_LLM_MODEL


MAX_CONTENT_ROOT_SAMPLE_CHARS = 6_000


class LLMContentRootValidation(BaseModel):
    is_single_complete_job_posting: bool = Field(
        description="Whether the extracted content root appears to contain exactly one complete job posting."
    )
    confidence: str = Field(description="One of low, medium, or high.")
    missing_sections: list[str] = Field(default_factory=list)
    noise_detected: list[str] = Field(default_factory=list)
    reason: str = Field(description="Short evidence-based explanation.")


class LLMContentRootValidatorUnavailable(RuntimeError):
    pass


def validate_content_root_with_llm(
    *,
    strategy: ContentRootStrategy,
    text: str,
    headings: list[str],
) -> ContentRootSemanticValidation:
    client, model = _openai_client_and_model()
    artifact = {
        "domain": strategy.domain,
        "selector": strategy.content_selector,
        "source": strategy.source.value,
        "text_length": strategy.validation.text_length,
        "structural_score": strategy.validation.structural_score,
        "headings": headings[:30],
        "sample": text[:MAX_CONTENT_ROOT_SAMPLE_CHARS],
    }

    try:
        response = client.responses.parse(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Validate whether a browser-extracted content root contains one complete job posting. "
                        "Use only the supplied artifact. Do not require every possible section, but check that the "
                        "content is not merely search results, navigation, similar jobs, legal text, or multiple job cards. "
                        "A small amount of surrounding page chrome is acceptable if the main posting is complete."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(artifact, ensure_ascii=True),
                },
            ],
            text_format=LLMContentRootValidation,
        )
    except Exception as error:
        raise LLMContentRootValidatorUnavailable(f"LLM content-root validator request failed: {error}") from error

    validation = response.output_parsed
    if validation is None:
        raise LLMContentRootValidatorUnavailable("LLM content-root validator returned no structured output.")

    return ContentRootSemanticValidation(
        required=True,
        attempted=True,
        passed=validation.is_single_complete_job_posting and validation.confidence.lower() in {"medium", "high"},
        confidence=validation.confidence.lower(),
        is_single_complete_job_posting=validation.is_single_complete_job_posting,
        missing_sections=validation.missing_sections,
        noise_detected=validation.noise_detected,
        reason=validation.reason,
        model=model,
    )


def _openai_client_and_model():
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMContentRootValidatorUnavailable("OPENAI_API_KEY is not set.")

    try:
        from openai import OpenAI
    except ImportError as error:
        raise LLMContentRootValidatorUnavailable(
            'OpenAI SDK is not installed. Install it with `pip install -e ".[dev,ai]"`.'
        ) from error

    return OpenAI(api_key=api_key), os.getenv("JOB_AGENT_LLM_MODEL", DEFAULT_LLM_MODEL)
