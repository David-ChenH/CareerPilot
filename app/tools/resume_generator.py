import json
import os
from typing import Any

from pydantic import BaseModel, Field

from app.artifacts import (
    RESUME_PROMPT_VERSION,
    RESUME_WORKFLOW_VERSION,
    ArtifactProvenance,
    artifact_provenance,
    configured_llm_model,
)
from app.config.env import load_local_env
from app.db.models import JobRecord
from app.tools.llm_job_chat import DEFAULT_LLM_MODEL
from app.tools.pdf_writer import build_simple_pdf


class ResumeSection(BaseModel):
    heading: str
    bullets: list[str] = Field(default_factory=list)


class ResumeDraft(BaseModel):
    title: str = Field(description="Resume document title.")
    sections: list[ResumeSection] = Field(description="Resume sections with bullet lists.")


class LLMResumeGeneratorUnavailable(RuntimeError):
    pass


class ResumeArtifact(BaseModel):
    pdf: bytes
    draft: ResumeDraft
    provenance: ArtifactProvenance


def generate_resume_pdf(
    profile: dict[str, Any],
    role_title: str,
    company: str | None = None,
    job: JobRecord | None = None,
    notes: str | None = None,
    use_llm: bool = True,
) -> bytes:
    return generate_resume_artifact(
        profile=profile,
        role_title=role_title,
        company=company,
        job=job,
        notes=notes,
        use_llm=use_llm,
    ).pdf


def generate_resume_artifact(
    profile: dict[str, Any],
    role_title: str,
    company: str | None = None,
    job: JobRecord | None = None,
    notes: str | None = None,
    use_llm: bool = True,
) -> ResumeArtifact:
    if use_llm:
        try:
            draft = generate_resume_draft_with_llm(profile, role_title, company=company, job=job, notes=notes)
            return ResumeArtifact(
                pdf=build_simple_pdf(draft.title, [(section.heading, section.bullets) for section in draft.sections]),
                draft=draft,
                provenance=artifact_provenance(
                    generator="llm",
                    workflow_version=RESUME_WORKFLOW_VERSION,
                    schema_version=1,
                    prompt_version=RESUME_PROMPT_VERSION,
                    model=configured_llm_model(DEFAULT_LLM_MODEL),
                ),
            )
        except Exception:
            pass

    title, sections = generate_resume_draft_deterministically(profile, role_title, company=company, job=job, notes=notes)
    draft = ResumeDraft(
        title=title,
        sections=[ResumeSection(heading=heading, bullets=bullets) for heading, bullets in sections],
    )
    return ResumeArtifact(
        pdf=build_simple_pdf(title, sections),
        draft=draft,
        provenance=artifact_provenance(
            generator="deterministic",
            workflow_version=RESUME_WORKFLOW_VERSION,
            schema_version=1,
        ),
    )


def generate_resume_draft_with_llm(
    profile: dict[str, Any],
    role_title: str,
    company: str | None = None,
    job: JobRecord | None = None,
    notes: str | None = None,
) -> ResumeDraft:
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMResumeGeneratorUnavailable("OPENAI_API_KEY is not set.")

    try:
        from openai import OpenAI
    except ImportError as error:
        raise LLMResumeGeneratorUnavailable(
            'OpenAI SDK is not installed. Install it with `pip install -e ".[dev,ai]"`.'
        ) from error

    target = f"{role_title}{f' at {company}' if company else ''}"
    client = OpenAI(api_key=api_key)
    response = client.responses.parse(
        model=configured_llm_model(DEFAULT_LLM_MODEL),
        input=[
            {
                "role": "system",
                "content": (
                    "Generate a truthful targeted resume draft from supplied local profile and job context. "
                    "Do not invent employers, metrics, degrees, projects, or technologies that are not present. "
                    "Position existing experience toward the target role. Return concise PDF-ready sections."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "target_role": target,
                        "profile": profile,
                        "job": job.model_dump() if job else None,
                        "notes": notes,
                    },
                    ensure_ascii=True,
                ),
            },
        ],
        text_format=ResumeDraft,
    )
    draft = response.output_parsed
    if draft is None:
        raise LLMResumeGeneratorUnavailable("LLM resume generator returned no structured output.")
    return draft


def generate_resume_draft_deterministically(
    profile: dict[str, Any],
    role_title: str,
    company: str | None = None,
    job: JobRecord | None = None,
    notes: str | None = None,
) -> tuple[str, list[tuple[str, list[str]]]]:
    title = profile.get("current_role", {}).get("title", "Software Engineer")
    identity = profile.get("positioning", {}).get("target_identity") or profile.get("positioning", {}).get("summary") or title
    target = f"{role_title}{f' at {company}' if company else ''}"
    skills = _pick(profile.get("technical_strengths", []), 12)
    highlights = _pick(profile.get("experience_highlights", []), 8)
    goals = _pick(profile.get("career_goals", []), 4)
    job_skills = _pick(job.skills if job else [], 8)
    resume_guidance = _pick((job.analysis or {}).get("guidance", {}).get("resume_guidance", []) if job else [], 5)

    sections = [
        ("Target Role", [target]),
        ("Professional Summary", [f"{identity} Targeting: {target}."]),
        ("Selected Technical Strengths", skills + job_skills),
        ("Experience Highlights", highlights),
        ("Role-Specific Positioning", resume_guidance or goals),
    ]
    if notes:
        sections.append(("User Notes", [notes]))
    sections.append(("Important", ["Draft generated from local CareerPilot profile. Review and edit before submitting."]))
    return f"Targeted Resume Draft - {target}", sections


def _pick(values: list[str], limit: int) -> list[str]:
    result = []
    seen = set()
    for value in values:
        clean = str(value).strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
        if len(result) >= limit:
            break
    return result
