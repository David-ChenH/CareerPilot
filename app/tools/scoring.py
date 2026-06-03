from pydantic import BaseModel, Field

class JobFit(BaseModel):
    score: int
    priority: str
    strong_matches: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    growth_areas: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    summary: str
    score_components: dict[str, int] = Field(default_factory=dict)
    recommendation: str | None = None
    transition_notes: list[str] = Field(default_factory=list)
    evidence: dict[str, list["EvidenceItem"]] = Field(default_factory=dict)


class EvidenceItem(BaseModel):
    claim: str
    evidence_from_job: str | None = None
    profile_signal: str | None = None
    severity: str | None = None
    confidence: str | None = None
    source: str = "analysis"
