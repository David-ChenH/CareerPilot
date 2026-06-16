from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ProfileIdentity(BaseModel):
    current_title: str = ""
    current_company: str = ""
    location: str | None = None
    years_experience: float | None = None
    tenure: str | None = None
    summary: str = ""
    target_identity: str = ""


class EducationEntry(BaseModel):
    school: str
    degree: str | None = None
    field: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    raw: str | None = None


class SkillEntry(BaseModel):
    name: str
    category: str = "general"
    proficiency: str = "working"
    evidence: list[str] = Field(default_factory=list)
    source: str | None = None


class ProjectEntry(BaseModel):
    name: str
    domain: str | None = None
    summary: str
    role: str | None = None
    technologies: list[str] = Field(default_factory=list)
    architecture_patterns: list[str] = Field(default_factory=list)
    impact_metrics: list[str] = Field(default_factory=list)
    source: str | None = None


class ProfilePreferences(BaseModel):
    target_roles: list[str] = Field(default_factory=list)
    career_goals: list[str] = Field(default_factory=list)
    learning_goals: list[str] = Field(default_factory=list)
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    unknown_or_to_confirm: list[str] = Field(default_factory=list)


class ProfileV1(BaseModel):
    profile_schema_version: Literal[1] = 1
    identity: ProfileIdentity
    background: list[str] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    skills: list[SkillEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    experience_highlights: list[str] = Field(default_factory=list)
    preferences: ProfilePreferences = Field(default_factory=ProfilePreferences)

    @field_validator("background", "experience_highlights")
    @classmethod
    def _dedupe_strings(cls, values: list[str]) -> list[str]:
        return _dedupe(values)

    @property
    def current_company(self) -> str | None:
        return self.identity.current_company or None

    @property
    def current_title(self) -> str:
        return self.identity.current_title or "Software Engineer"

    @property
    def target_identity(self) -> str:
        return self.identity.target_identity or self.identity.summary or self.current_title

    @property
    def skill_names(self) -> list[str]:
        return _dedupe([skill.name for skill in self.skills])

    @property
    def target_roles(self) -> list[str]:
        return self.preferences.target_roles

    @property
    def learning_goals(self) -> list[str]:
        return self.preferences.learning_goals

    @property
    def career_goals(self) -> list[str]:
        return self.preferences.career_goals

    def resume_highlights(self, limit: int = 8) -> list[str]:
        project_highlights = [
            highlight
            for project in self.projects
            for highlight in [project.summary, *project.impact_metrics]
            if highlight
        ]
        return _dedupe([*self.experience_highlights, *project_highlights])[:limit]

    def to_runtime_context(self) -> dict[str, Any]:
        """Return structured profile plus temporary legacy projections.

        The structured keys are the official schema. The legacy projections keep
        existing scorers, resume generation, and profile-update flows working
        while they are moved to typed profile accessors.
        """
        data = self.model_dump(mode="json", exclude_none=True)
        data.update(
            {
                "current_role": {
                    "title": self.identity.current_title,
                    "company": self.identity.current_company,
                    "experience_years": self.identity.years_experience,
                    **({"location": self.identity.location} if self.identity.location else {}),
                    **({"tenure": self.identity.tenure} if self.identity.tenure else {}),
                },
                "positioning": {
                    "summary": self.identity.summary,
                    "target_identity": self.identity.target_identity,
                },
                "core_background": self.background,
                "technical_strengths": self.skill_names,
                "target_roles": self.target_roles,
                "career_goals": self.career_goals,
                "learning_goals": self.learning_goals,
                "must_have": self.preferences.must_have,
                "nice_to_have": self.preferences.nice_to_have,
                "avoid": self.preferences.avoid,
                "unknown_or_to_confirm": self.preferences.unknown_or_to_confirm,
            }
        )
        data["education"] = [
            entry.raw
            or ", ".join(
                part
                for part in [
                    entry.school,
                    entry.degree,
                    entry.field,
                    _year_range(entry.start_year, entry.end_year),
                ]
                if part
            )
            for entry in self.education
        ]
        return data


def load_profile_v1(raw: dict[str, Any]) -> ProfileV1:
    if raw.get("profile_schema_version") == 1 and "identity" in raw:
        return ProfileV1.model_validate(raw)
    return ProfileV1.model_validate(_legacy_profile_to_v1(raw))


def _legacy_profile_to_v1(raw: dict[str, Any]) -> dict[str, Any]:
    current_role = raw.get("current_role") if isinstance(raw.get("current_role"), dict) else {}
    positioning = raw.get("positioning") if isinstance(raw.get("positioning"), dict) else {}
    return {
        "profile_schema_version": 1,
        "identity": {
            "current_title": current_role.get("title", ""),
            "current_company": current_role.get("company", ""),
            "location": current_role.get("location"),
            "years_experience": current_role.get("experience_years"),
            "tenure": current_role.get("tenure"),
            "summary": positioning.get("summary", ""),
            "target_identity": positioning.get("target_identity", ""),
        },
        "background": _as_string_list(raw.get("core_background")),
        "education": [_parse_legacy_education(value) for value in _as_string_list(raw.get("education"))],
        "skills": [
            {
                "name": value,
                "category": _infer_skill_category(value),
                "proficiency": "strong",
            }
            for value in _as_string_list(raw.get("technical_strengths"))
        ],
        "projects": [],
        "experience_highlights": _as_string_list(raw.get("experience_highlights")),
        "preferences": {
            "target_roles": _as_string_list(raw.get("target_roles")),
            "career_goals": _as_string_list(raw.get("career_goals")),
            "learning_goals": _as_string_list(raw.get("learning_goals")),
            "must_have": _as_string_list(raw.get("must_have")),
            "nice_to_have": _as_string_list(raw.get("nice_to_have")),
            "avoid": _as_string_list(raw.get("avoid")),
            "unknown_or_to_confirm": _as_string_list(raw.get("unknown_or_to_confirm")),
        },
    }


def _parse_legacy_education(value: str) -> dict[str, Any]:
    parts = [part.strip() for part in value.replace(" - ", ", ").split(",") if part.strip()]
    years = [int(part) for part in parts if part.isdigit() and len(part) == 4]
    return {
        "school": parts[0] if parts else value,
        "field": parts[1] if len(parts) > 1 else None,
        "start_year": years[0] if years else None,
        "end_year": years[1] if len(years) > 1 else None,
        "raw": value,
    }


def _infer_skill_category(value: str) -> str:
    lowered = value.lower()
    if lowered in {"python", "java", "typescript", "javascript", "scala", "c++", "c#"}:
        return "language"
    if any(term in lowered for term in ["aws", "lambda", "dynamodb", "ecs", "gateway", "cloudwatch", "s3", "cdk"]):
        return "cloud"
    if any(term in lowered for term in ["llm", "agent", "bedrock", "kiro", "structured outputs"]):
        return "ai"
    if any(term in lowered for term in ["architecture", "distributed", "workflow", "state", "control plane", "data plane"]):
        return "architecture"
    return "general"


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return _dedupe([str(item).strip() for item in value if str(item).strip()])
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _dedupe(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _year_range(start_year: int | None, end_year: int | None) -> str | None:
    if start_year and end_year:
        return f"{start_year} - {end_year}"
    if start_year:
        return str(start_year)
    return None
