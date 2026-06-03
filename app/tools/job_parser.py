import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field


SKILL_ALIASES = {
    "agent": ["agentic", "multi-agent", "agent orchestration", "ai agent"],
    "api": ["api", "apis", "rest", "grpc"],
    "backend": ["backend", "back-end", "server-side"],
    "c#": ["c#", "c sharp", "csharp"],
    "c++": ["c++", "cplusplus"],
    "cloud": ["cloud", "aws", "amazon web services", "gcp", "google cloud", "azure"],
    "docker": ["docker", "containers", "containerized", "containerization"],
    "distributed systems": ["distributed system", "distributed systems"],
    "eks": ["eks", "elastic kubernetes service", "amazon elastic kubernetes service"],
    "fastapi": ["fastapi"],
    "flink": ["flink", "apache flink"],
    "kubernetes": ["kubernetes", "k8s"],
    "java": ["java"],
    "llm": ["llm", "large language model", "generative ai", "genai"],
    "python": ["python"],
    "rag": ["rag", "retrieval augmented generation", "retrieval-augmented generation"],
    "serverless": ["lambda", "serverless", "cloud functions"],
    "workflow orchestration": ["step functions", "state machine", "workflow orchestration", "temporal", "airflow"],
    "vector database": ["vector database", "vector db", "embedding"],
}

KNOWN_COMPANY_DOMAINS = {
    "metacareers.com": "Meta",
    "meta.com": "Meta",
    "openai.com": "OpenAI",
    "anthropic.com": "Anthropic",
    "microsoft.com": "Microsoft",
    "amazon.jobs": "Amazon",
    "apple.com": "Apple",
    "google.com": "Google",
    "netflix.com": "Netflix",
}

GENERIC_PAGE_TITLES = {
    "careers",
    "jobs",
    "job search",
    "job details",
    "meta careers",
}


class ParsedJob(BaseModel):
    title: str | None = None
    company: str | None = None
    location: str | None = None
    seniority: str | None = None
    skills: list[str] = Field(default_factory=list)
    description: str
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    preferred_qualifications: list[str] = Field(default_factory=list)
    ambiguous_qualifications: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    accepted_skill_alternatives: list[str] = Field(default_factory=list)
    compensation: str | None = None
    work_authorization: str | None = None
    role_focus: list[str] = Field(default_factory=list)
    team_business: str | None = None


def parse_job_description(
    description: str,
    source_url: str | None = None,
    page_title: str | None = None,
) -> ParsedJob:
    text = description.strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    return ParsedJob(
        title=_extract_title(lines, page_title),
        company=_extract_company(text, source_url, page_title),
        location=_extract_labeled_value(text, "location"),
        seniority=_extract_seniority(text),
        skills=_extract_skills(text),
        accepted_skill_alternatives=_extract_accepted_skill_alternatives(text),
        description=text,
    )


def _extract_title(lines: list[str], page_title: str | None = None) -> str | None:
    page_title_candidate = _clean_title(page_title)
    if page_title_candidate:
        return page_title_candidate

    if not lines:
        return None
    for line in lines[:12]:
        cleaned_line = _clean_title(line)
        if cleaned_line:
            return cleaned_line
    return None


def _extract_labeled_value(text: str, label: str) -> str | None:
    match = re.search(rf"^{label}\s*:\s*(.+)$", text, flags=re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else None


def _extract_company(text: str, source_url: str | None, page_title: str | None) -> str | None:
    labeled_company = _extract_labeled_value(text, "company")
    if labeled_company:
        return labeled_company

    domain_company = _company_from_url(source_url)
    if domain_company:
        return domain_company

    if page_title:
        title_parts = re.split(r"\s[-|]\s", page_title)
        for part in title_parts:
            cleaned_part = part.strip()
            if cleaned_part.lower() not in GENERIC_PAGE_TITLES and len(cleaned_part) <= 60:
                return cleaned_part

    return None


def _company_from_url(source_url: str | None) -> str | None:
    if not source_url:
        return None
    host = urlparse(source_url).netloc.lower().removeprefix("www.")
    for domain, company in KNOWN_COMPANY_DOMAINS.items():
        if host == domain or host.endswith(f".{domain}"):
            return company
    return None


def _clean_title(value: str | None) -> str | None:
    if not value:
        return None

    title = re.sub(r"^job title:\s*", "", value.strip(), flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title)
    if not title or len(title) > 140:
        return None

    lowered = title.lower()
    if lowered in GENERIC_PAGE_TITLES:
        return None

    title_parts = [
        part.strip()
        for part in re.split(r"\s[-|]\s", title)
        if part.strip() and part.strip().lower() not in GENERIC_PAGE_TITLES
    ]
    if title_parts:
        title = title_parts[0]

    if not _looks_like_job_title(title):
        return None
    return title


def _looks_like_job_title(title: str) -> bool:
    lowered = title.lower()
    job_keywords = [
        "engineer",
        "developer",
        "manager",
        "scientist",
        "designer",
        "architect",
        "analyst",
        "researcher",
        "lead",
        "specialist",
        "consultant",
        "intern",
        "director",
        "product",
        "platform",
        "infrastructure",
    ]
    return any(keyword in lowered for keyword in job_keywords)


def _extract_seniority(text: str) -> str | None:
    lowered = text.lower()
    if re.search(r"\b(staff|principal)\b", lowered):
        return "staff/principal"
    if re.search(r"\b(senior|sr\.?)\b", lowered):
        return "senior"
    if re.search(r"\b(mid-level|mid level|software engineer ii)\b", lowered):
        return "mid-level"
    if re.search(r"\b(junior|entry level|new grad)\b", lowered):
        return "junior"
    return None


def _extract_skills(text: str) -> list[str]:
    lowered = text.lower()
    skills = []
    for normalized, aliases in SKILL_ALIASES.items():
        if any(_contains_alias(lowered, alias) for alias in aliases):
            skills.append(normalized)
    return sorted(skills)


def _extract_accepted_skill_alternatives(text: str) -> list[str]:
    alternatives = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        lowered = sentence.lower()
        if (
            ("including, but not limited to" in lowered or " or " in lowered)
            and len(_language_terms(lowered)) >= 2
        ):
            alternatives.append(" ".join(sentence.split()))
    return alternatives


def _language_terms(text: str) -> set[str]:
    lowered = text.lower()
    return {
        language
        for language, pattern in {
            "c": r"(?<![a-z0-9+#])c(?![a-z0-9+#])",
            "c++": r"c\+\+",
            "c#": r"c#|c sharp|csharp",
            "java": r"(?<![a-z0-9])java(?![a-z0-9])",
            "python": r"(?<![a-z0-9])python(?![a-z0-9])",
        }.items()
        if re.search(pattern, lowered)
    }


def _contains_alias(lowered_text: str, alias: str) -> bool:
    escaped_alias = re.escape(alias.lower())
    pattern = rf"(?<![a-z0-9]){escaped_alias}(?![a-z0-9])"
    return re.search(pattern, lowered_text) is not None
