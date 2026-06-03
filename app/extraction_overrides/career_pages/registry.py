from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, field_validator


DEFAULT_OVERRIDES_PATH = Path(__file__).parent


class CareerPageOverrideQualityChecks(BaseModel):
    min_characters: int = Field(default=500, ge=200)
    max_characters: int = Field(default=20_000, ge=500)
    expected_signals: list[str] = Field(default_factory=list)
    excluded_signals: list[str] = Field(default_factory=list)

    @field_validator("max_characters")
    @classmethod
    def validate_max_characters(cls, value: int, info) -> int:
        minimum = info.data.get("min_characters", 500)
        if value <= minimum:
            raise ValueError("max_characters must be greater than min_characters")
        return value


class CareerPageExtractionOverride(BaseModel):
    version: int = Field(ge=1)
    domains: list[str] = Field(min_length=1)
    content_selector: str = Field(min_length=1, max_length=300)
    heading_selector: str = Field(default="h1, h2, h3, h4, h5, h6", min_length=1, max_length=300)
    quality_checks: CareerPageOverrideQualityChecks = Field(default_factory=CareerPageOverrideQualityChecks)

    @field_validator("domains")
    @classmethod
    def normalize_domains(cls, domains: list[str]) -> list[str]:
        normalized = [domain.strip().lower() for domain in domains if domain.strip()]
        if not normalized:
            raise ValueError("at least one non-empty domain is required")
        return normalized


class CareerPageExtractionOverrideRegistry:
    def __init__(self, root: Path = DEFAULT_OVERRIDES_PATH) -> None:
        self.root = root

    def load(self, name: str) -> CareerPageExtractionOverride:
        override_path = self.root / name / "override.yaml"
        if not override_path.exists():
            raise FileNotFoundError(f"Career-page extraction override {name!r} is missing override.yaml.")
        with override_path.open("r", encoding="utf-8") as override_file:
            payload = yaml.safe_load(override_file) or {}
        return CareerPageExtractionOverride.model_validate(payload)

    def find_for_url(self, url: str) -> CareerPageExtractionOverride | None:
        domain = urlparse(url).netloc.lower()
        for override_path in sorted(self.root.iterdir()):
            if not override_path.is_dir() or not (override_path / "override.yaml").exists():
                continue
            override = self.load(override_path.name)
            if domain in override.domains:
                return override
        return None
