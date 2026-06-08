from pydantic import BaseModel, Field

from app.tools.job_fit_taxonomy import ConcernCode, GapCode, GrowthAreaCode


class JobFit(BaseModel):
    score: int
    priority: str
    strong_matches: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    growth_areas: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    concern_codes: list[ConcernCode] = Field(default_factory=list)
    gap_codes: list[GapCode] = Field(default_factory=list)
    growth_area_codes: list[GrowthAreaCode] = Field(default_factory=list)
    uncategorized_observations: list[str] = Field(default_factory=list)
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
