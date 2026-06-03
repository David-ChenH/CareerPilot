from enum import StrEnum

from pydantic import BaseModel, Field


MIN_READABLE_TEXT_LENGTH = 200
MIN_STRUCTURAL_SCORE = 4
RESPONSIBILITY_SIGNALS = ["responsibilit"]
QUALIFICATION_SIGNALS = ["qualification", "requirement"]
EXPERIENCE_SIGNALS = ["experience"]
POSITIVE_SIGNALS = [
    *RESPONSIBILITY_SIGNALS,
    *QUALIFICATION_SIGNALS,
    "preferred",
    *EXPERIENCE_SIGNALS,
    "about the job",
]
NOISE_SIGNALS = ["cookie", "privacy", "sign in", "similar jobs", "search jobs"]


class ContentRootStrategySource(StrEnum):
    LEARNED_OBSERVATION = "learned_observation"
    REVIEWED_OVERRIDE = "reviewed_override"
    BOUNDED_DISCOVERY = "bounded_discovery"


class ContentRootValidationEvidence(BaseModel):
    text_length: int = Field(ge=0)
    structural_score: int
    has_responsibility_signal: bool
    has_qualification_signal: bool
    has_experience_signal: bool
    noise_signals: list[str] = Field(default_factory=list)
    passed: bool


class ContentRootSemanticValidation(BaseModel):
    required: bool = False
    attempted: bool = False
    passed: bool | None = None
    confidence: str | None = None
    is_single_complete_job_posting: bool | None = None
    missing_sections: list[str] = Field(default_factory=list)
    noise_detected: list[str] = Field(default_factory=list)
    reason: str | None = None
    model: str | None = None
    error: str | None = None


class ContentRootStrategy(BaseModel):
    domain: str
    content_selector: str
    heading_selector: str = "h1, h2, h3, h4, h5, h6"
    source: ContentRootStrategySource
    validation: ContentRootValidationEvidence
    semantic_validation: ContentRootSemanticValidation | None = None


def validate_content_root(text: str) -> ContentRootValidationEvidence:
    lowered = text.lower()
    score = 0
    if len(text) >= MIN_READABLE_TEXT_LENGTH:
        score = 1 + min(len(text) // 2_000, 4)
        score += sum(2 for signal in POSITIVE_SIGNALS if signal in lowered)
        score -= sum(1 for signal in NOISE_SIGNALS if signal in lowered)
    return ContentRootValidationEvidence(
        text_length=len(text),
        structural_score=score,
        has_responsibility_signal=any(signal in lowered for signal in RESPONSIBILITY_SIGNALS),
        has_qualification_signal=any(signal in lowered for signal in QUALIFICATION_SIGNALS),
        has_experience_signal=any(signal in lowered for signal in EXPERIENCE_SIGNALS),
        noise_signals=[signal for signal in NOISE_SIGNALS if signal in lowered],
        passed=len(text) >= MIN_READABLE_TEXT_LENGTH and score >= MIN_STRUCTURAL_SCORE,
    )
