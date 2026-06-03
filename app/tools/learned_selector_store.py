import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.tools.content_root_strategy import (
    ContentRootSemanticValidation,
    ContentRootStrategy,
    ContentRootValidationEvidence,
)


DEFAULT_SELECTOR_PATH = Path("data/career_page_selectors.local.json")
PROMOTION_SUCCESS_COUNT = 2


class LearnedCareerPageSelector(BaseModel):
    domain: str
    content_selector: str
    heading_selector: str = "h1, h2, h3, h4, h5, h6"
    status: str = "candidate"
    successful_extractions: int = 0
    failed_extractions: int = 0
    last_score: int = 0
    validation: ContentRootValidationEvidence | None = None
    semantic_validation: ContentRootSemanticValidation | None = None
    updated_at: str


class LearnedSelectorStore:
    def __init__(self, path: Path | None = None) -> None:
        configured_path = os.getenv("CAREERPILOT_SELECTOR_STORE_PATH") or os.getenv("CAREERPILOT_RECIPE_STORE_PATH")
        self.path = path or (Path(configured_path) if configured_path else DEFAULT_SELECTOR_PATH)

    def get_promoted(self, url: str) -> LearnedCareerPageSelector | None:
        selector = self.get(url)
        return selector if selector and selector.status == "promoted" else None

    def get(self, url: str) -> LearnedCareerPageSelector | None:
        domain = _domain(url)
        payload = self._read()
        selector = payload.get(domain)
        return LearnedCareerPageSelector.model_validate(selector) if selector else None

    def record_success(self, strategy: ContentRootStrategy) -> LearnedCareerPageSelector:
        url = f"https://{strategy.domain}"
        selector = strategy.content_selector
        domain = _domain(url)
        payload = self._read()
        current = LearnedCareerPageSelector.model_validate(payload[domain]) if domain in payload else None
        successes = current.successful_extractions + 1 if current and current.content_selector == selector else 1
        failures = current.failed_extractions if current and current.content_selector == selector else 0
        status = "promoted" if successes >= PROMOTION_SUCCESS_COUNT and _semantic_allows_promotion(strategy) else "candidate"
        observation = LearnedCareerPageSelector(
            domain=domain,
            content_selector=selector,
            status=status,
            successful_extractions=successes,
            failed_extractions=failures,
            last_score=strategy.validation.structural_score,
            validation=strategy.validation,
            semantic_validation=strategy.semantic_validation,
            updated_at=_now(),
        )
        payload[domain] = observation.model_dump(mode="json")
        self._write(payload)
        return observation

    def record_failure(self, url: str, selector: str) -> LearnedCareerPageSelector | None:
        domain = _domain(url)
        payload = self._read()
        current_payload = payload.get(domain)
        if not current_payload:
            return None
        observation = LearnedCareerPageSelector.model_validate(current_payload)
        if observation.content_selector != selector:
            return observation
        observation.failed_extractions += 1
        observation.status = "candidate"
        observation.updated_at = _now()
        payload[domain] = observation.model_dump(mode="json")
        self._write(payload)
        return observation

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary_path.replace(self.path)


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _semantic_allows_promotion(strategy: ContentRootStrategy) -> bool:
    semantic_validation = strategy.semantic_validation
    if semantic_validation is None or not semantic_validation.required:
        return True
    return semantic_validation.passed is True
