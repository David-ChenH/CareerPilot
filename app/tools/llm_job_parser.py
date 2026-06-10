import json
import os

from pydantic import BaseModel, Field

from app.config.env import load_local_env
from app.tools.job_parser import ParsedJob
from app.tools.job_extraction import ExtractedJobPosting
from app.tools.text_budget import JOB_SIGNAL_KEYWORDS, compact_job_text


DEFAULT_LLM_MODEL = "gpt-4o-mini"
MAX_DESCRIPTION_CHARS = 20_000
CHUNK_CHARS = 12_000
CHUNK_OVERLAP_CHARS = 800
MAX_CHUNKS = 8
MAX_STRUCTURE_ARTIFACT_CHARS = 16_000


class LLMParsedJob(BaseModel):
    title: str | None = Field(default=None, description="The exact job title.")
    company: str | None = Field(default=None, description="The hiring company.")
    location: str | None = Field(default=None, description="Job location or remote/hybrid status.")
    seniority: str | None = Field(default=None, description="Seniority such as junior, mid-level, senior, staff/principal.")
    skills: list[str] = Field(default_factory=list, description="Normalized technical and domain skills.")
    required_skills: list[str] = Field(default_factory=list, description="Skills or technologies that appear required.")
    preferred_skills: list[str] = Field(default_factory=list, description="Skills or technologies that appear preferred or nice-to-have.")
    accepted_skill_alternatives: list[str] = Field(
        default_factory=list,
        description="Qualification phrases where any one of several listed skills or languages satisfies the requirement.",
    )
    responsibilities: list[str] = Field(default_factory=list, description="Core responsibilities.")
    requirements: list[str] = Field(default_factory=list, description="Required qualifications.")
    preferred_qualifications: list[str] = Field(default_factory=list, description="Preferred or nice-to-have qualifications.")
    ambiguous_qualifications: list[str] = Field(
        default_factory=list,
        description="Qualification statements whose required/preferred tier is unclear because headings or grouping are missing.",
    )
    compensation: str | None = Field(default=None, description="Compensation range if explicitly present.")
    work_authorization: str | None = Field(default=None, description="Work authorization or visa notes if explicitly present.")
    role_focus: list[str] = Field(default_factory=list, description="Role focus areas such as backend, platform, ML infrastructure, frontend, research.")
    team_business: str | None = Field(
        default=None,
        description=(
            "A concise description of what the hiring team or product/business area does. "
            "Prefer concrete product, platform, customer, or business domain facts from the posting."
        ),
    )


class LLMJobParserUnavailable(RuntimeError):
    pass


def parse_job_with_llm(
    description: str,
    deterministic_job: ParsedJob,
    source_url: str | None = None,
    page_title: str | None = None,
    extracted_posting: ExtractedJobPosting | None = None,
) -> ParsedJob:
    clipped_description = description[:MAX_DESCRIPTION_CHARS]
    llm_job = _parse_llm_job_text(
        text=clipped_description,
        source_url=source_url,
        page_title=page_title,
        chunk_label=None,
        extracted_posting=extracted_posting,
    )

    return _to_parsed_job(llm_job, deterministic_job, description.strip())


def parse_large_job_with_llm(
    description: str,
    deterministic_job: ParsedJob,
    source_url: str | None = None,
    page_title: str | None = None,
    final_description: str | None = None,
    extracted_posting: ExtractedJobPosting | None = None,
) -> ParsedJob:
    chunks = select_job_chunks(description)
    if not chunks:
        raise LLMJobParserUnavailable("No chunks were selected for oversized job parsing.")

    partial_jobs = []
    failures = []
    for index, chunk in enumerate(chunks, start=1):
        try:
            partial_jobs.append(
                _parse_llm_job_text(
                    text=chunk,
                    source_url=source_url,
                    page_title=page_title,
                    chunk_label=f"chunk {index} of {len(chunks)}",
                    extracted_posting=extracted_posting if index == 1 else None,
                )
            )
        except LLMJobParserUnavailable as error:
            failures.append(str(error))

    if not partial_jobs:
        detail = "; ".join(failures[:3]) if failures else "No chunk parser output."
        raise LLMJobParserUnavailable(f"Chunked LLM parser returned no usable output. {detail}")

    merged_job = _merge_llm_jobs(partial_jobs)
    safe_description = final_description or compact_job_text(description).text
    return _to_parsed_job(merged_job, deterministic_job, safe_description.strip())


def select_job_chunks(description: str) -> list[str]:
    text = _normalize_for_chunking(description)
    if len(text) <= CHUNK_CHARS:
        return [text] if text else []

    candidates = [_chunk_at(text, 0)]
    lower_text = text.lower()
    for keyword in JOB_SIGNAL_KEYWORDS:
        start = 0
        while True:
            index = lower_text.find(keyword, start)
            if index < 0:
                break
            candidates.append(_chunk_at(text, max(0, index - CHUNK_OVERLAP_CHARS)))
            start = index + len(keyword)
            if len(candidates) >= MAX_CHUNKS * 2:
                break
    candidates.append(_chunk_at(text, max(0, len(text) - CHUNK_CHARS)))

    return _rank_unique_chunks(candidates)[:MAX_CHUNKS]


def _parse_llm_job_text(
    text: str,
    source_url: str | None,
    page_title: str | None,
    chunk_label: str | None,
    extracted_posting: ExtractedJobPosting | None = None,
) -> LLMParsedJob:
    client, model = _openai_client_and_model()
    label = f"{chunk_label}\n" if chunk_label else ""

    structured_sections = ""
    if extracted_posting and extracted_posting.sections:
        structured_sections = (
            "\n\nStructure-preserving extraction artifact:\n"
            + _structure_artifact_json(extracted_posting)
        )

    try:
        response = client.responses.parse(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Extract structured job posting information. "
                        "Use only facts present in the text, URL, or page title. "
                        "When a structure-preserving extraction artifact is supplied, classify its ordered sections semantically. "
                        "Use source headings and grouped items as evidence, but do not rely on a fixed catalog of heading names. "
                        "If a field is not present, leave it null or empty. "
                        "Extract technologies and skills even if they are not common or not listed in any predefined map. "
                        "Normalize skills to concise names like Python, Amazon EKS, Apache Flink, Kubernetes, LLM, backend, workflow orchestration. "
                        "Preserve qualification strength carefully. Put only explicitly required, minimum, or must-have qualifications "
                        "into requirements and required_skills. Put preferred, optional, nice-to-have, bonus, or ambiguous unlabelled "
                        "qualification bullets into preferred_qualifications and preferred_skills. If several languages are connected "
                        "by 'or', 'either', 'one of', 'one or more', or introduced with phrases such as "
                        "'including, but not limited to' or 'such as', preserve them as accepted alternatives rather than "
                        "implying that every language is individually required. Store those phrases in accepted_skill_alternatives and "
                        "do not repeat each option in required_skills. If education or experience paths appear contradictory, or the "
                        "text appears flattened without reliable section headings, preserve the affected statements in "
                        "ambiguous_qualifications instead of guessing that every statement is required. "
                        "For team_business, summarize the team's business or product purpose in one short sentence, not the candidate responsibilities. "
                        "If this is only one chunk of a larger page, extract only facts supported by this chunk."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Source URL: {source_url or 'unknown'}\n"
                        f"Page title: {page_title or 'unknown'}\n\n"
                        f"{label}Job page text:\n{text}"
                        f"{structured_sections}"
                    ),
                },
            ],
            text_format=LLMParsedJob,
        )
    except Exception as error:
        raise LLMJobParserUnavailable(f"LLM parser request failed: {error}") from error

    llm_job = response.output_parsed
    if llm_job is None:
        raise LLMJobParserUnavailable("LLM parser returned no structured output.")
    return llm_job


def _structure_artifact_json(extracted_posting: ExtractedJobPosting) -> str:
    payload = extracted_posting.model_dump()
    serialized = json.dumps(payload, ensure_ascii=True)
    if len(serialized) <= MAX_STRUCTURE_ARTIFACT_CHARS:
        return serialized

    compact_payload = {
        "metadata": payload["metadata"],
        "sections": [],
        "extraction_source": payload["extraction_source"],
        "warnings": payload["warnings"],
    }
    for section in payload["sections"]:
        compact_section = {
            "heading": section["heading"],
            "items": [],
            "source": section["source"],
            "order": section["order"],
        }
        for item in section["items"]:
            candidate_section = {
                **compact_section,
                "items": [*compact_section["items"], item[:1_000]],
            }
            candidate_payload = {
                **compact_payload,
                "sections": [*compact_payload["sections"], candidate_section],
            }
            if len(json.dumps(candidate_payload, ensure_ascii=True)) > MAX_STRUCTURE_ARTIFACT_CHARS:
                break
            compact_section = candidate_section

        candidate_payload = {
            **compact_payload,
            "sections": [*compact_payload["sections"], compact_section],
        }
        if len(json.dumps(candidate_payload, ensure_ascii=True)) > MAX_STRUCTURE_ARTIFACT_CHARS:
            break
        compact_payload = candidate_payload

    return json.dumps(compact_payload, ensure_ascii=True)


def _openai_client_and_model():
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMJobParserUnavailable("OPENAI_API_KEY is not set.")

    try:
        from openai import OpenAI
    except ImportError as error:
        raise LLMJobParserUnavailable(
            'OpenAI SDK is not installed. Install it with `pip install -e ".[dev,ai]"`.'
        ) from error

    return OpenAI(api_key=api_key), os.getenv("JOB_AGENT_LLM_MODEL", DEFAULT_LLM_MODEL)


def _to_parsed_job(llm_job: LLMParsedJob, deterministic_job: ParsedJob, description: str) -> ParsedJob:
    return ParsedJob(
        title=llm_job.title or deterministic_job.title,
        company=llm_job.company or deterministic_job.company,
        location=llm_job.location or deterministic_job.location,
        seniority=llm_job.seniority or deterministic_job.seniority,
        skills=_merge_skills(deterministic_job.skills, llm_job.skills),
        description=description.strip(),
        responsibilities=llm_job.responsibilities,
        requirements=llm_job.requirements,
        preferred_qualifications=llm_job.preferred_qualifications,
        ambiguous_qualifications=llm_job.ambiguous_qualifications,
        required_skills=_remove_accepted_alternative_skills(
            llm_job.required_skills,
            llm_job.accepted_skill_alternatives,
        ),
        preferred_skills=llm_job.preferred_skills,
        accepted_skill_alternatives=llm_job.accepted_skill_alternatives,
        compensation=llm_job.compensation,
        work_authorization=llm_job.work_authorization,
        role_focus=llm_job.role_focus,
        team_business=llm_job.team_business,
    )


def _merge_llm_jobs(jobs: list[LLMParsedJob]) -> LLMParsedJob:
    return LLMParsedJob(
        title=_first_text(job.title for job in jobs),
        company=_first_text(job.company for job in jobs),
        location=_first_text(job.location for job in jobs),
        seniority=_first_text(job.seniority for job in jobs),
        skills=_merge_strings(*(job.skills for job in jobs)),
        required_skills=_merge_strings(*(job.required_skills for job in jobs)),
        preferred_skills=_merge_strings(*(job.preferred_skills for job in jobs)),
        accepted_skill_alternatives=_merge_strings(*(job.accepted_skill_alternatives for job in jobs)),
        responsibilities=_merge_strings(*(job.responsibilities for job in jobs)),
        requirements=_merge_strings(*(job.requirements for job in jobs)),
        preferred_qualifications=_merge_strings(*(job.preferred_qualifications for job in jobs)),
        ambiguous_qualifications=_merge_strings(*(job.ambiguous_qualifications for job in jobs)),
        compensation=_first_text(job.compensation for job in jobs),
        work_authorization=_first_text(job.work_authorization for job in jobs),
        role_focus=_merge_strings(*(job.role_focus for job in jobs)),
        team_business=_first_text(job.team_business for job in jobs),
    )


def _merge_skills(deterministic_skills: list[str], llm_skills: list[str]) -> list[str]:
    normalized_skills = {
        skill.strip().lower(): skill.strip()
        for skill in [*deterministic_skills, *llm_skills]
        if skill and skill.strip()
    }
    return sorted(normalized_skills.values(), key=str.lower)


def _merge_strings(*groups: list[str]) -> list[str]:
    merged = {}
    for group in groups:
        for value in group:
            clean_value = " ".join(value.strip().split())
            if clean_value:
                merged.setdefault(clean_value.lower(), clean_value)
    return list(merged.values())


def _remove_accepted_alternative_skills(required_skills: list[str], alternatives: list[str]) -> list[str]:
    alternatives_text = " ".join(alternatives).lower()
    return [skill for skill in required_skills if skill.lower() not in alternatives_text]


def _first_text(values) -> str | None:
    for value in values:
        if value and value.strip():
            return value.strip()
    return None


def _normalize_for_chunking(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    useful_lines = []
    previous = None
    for line in lines:
        if not line:
            continue
        if line == previous:
            continue
        useful_lines.append(line)
        previous = line
    return "\n".join(useful_lines).strip()


def _chunk_at(text: str, start: int) -> str:
    start = max(0, min(start, len(text)))
    if start > 0:
        next_newline = text.find("\n", start)
        if 0 <= next_newline < start + CHUNK_OVERLAP_CHARS:
            start = next_newline + 1
    end = min(len(text), start + CHUNK_CHARS)
    if end < len(text):
        previous_newline = text.rfind("\n", start, end)
        if previous_newline > start + CHUNK_CHARS // 2:
            end = previous_newline
    return text[start:end].strip()


def _rank_unique_chunks(chunks: list[str]) -> list[str]:
    scored_chunks = []
    seen = set()
    for index, chunk in enumerate(chunks):
        if not chunk:
            continue
        fingerprint = chunk[:700]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        lower_chunk = chunk.lower()
        score = sum(3 for keyword in JOB_SIGNAL_KEYWORDS if keyword in lower_chunk)
        score += sum(1 for term in ["engineer", "software", "build", "cloud", "distributed", "kubernetes", "python", "java"] if term in lower_chunk)
        if index == 0:
            score += 2
        scored_chunks.append((score, -index, chunk))
    scored_chunks.sort(reverse=True)
    return [chunk for _score, _negative_index, chunk in scored_chunks]
