from copy import deepcopy
from typing import Callable


CURRENT_ANALYSIS_SCHEMA_VERSION = 5

AnalysisMigration = Callable[[dict], dict]


def migrate_analysis_payload(payload: dict | None, from_version: int | None = None) -> tuple[dict | None, int]:
    if payload is None:
        return None, CURRENT_ANALYSIS_SCHEMA_VERSION

    migrated = deepcopy(payload)
    version = from_version or 1
    while version < CURRENT_ANALYSIS_SCHEMA_VERSION:
        migration = ANALYSIS_MIGRATIONS.get(version)
        if migration is None:
            raise ValueError(f"Missing analysis payload migration from schema version {version}.")
        migrated = migration(migrated)
        version += 1
    return migrated, version


def _migrate_v1_to_v2(payload: dict) -> dict:
    guidance = payload.get("guidance")
    if not isinstance(guidance, dict):
        return payload

    guidance.pop("risk_summary", None)
    evidence = guidance.get("evidence")
    if isinstance(evidence, dict):
        evidence.pop("risk_summary", None)
    return payload


def _migrate_v2_to_v3(payload: dict) -> dict:
    fit = payload.get("fit")
    if isinstance(fit, dict):
        fit.setdefault("growth_areas", [])
    return payload


def _migrate_v3_to_v4(payload: dict) -> dict:
    payload.pop("baseline_fit", None)
    return payload


def _migrate_v4_to_v5(payload: dict) -> dict:
    payload.setdefault("extracted_posting", None)
    return payload


ANALYSIS_MIGRATIONS: dict[int, AnalysisMigration] = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
    3: _migrate_v3_to_v4,
    4: _migrate_v4_to_v5,
}
