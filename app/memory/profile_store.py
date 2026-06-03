from pathlib import Path
from typing import Any
import json
from datetime import datetime, timezone

import yaml


DEFAULT_PROFILE_PATH = Path(__file__).with_name("profile.local.yaml")
EXAMPLE_PROFILE_PATH = Path(__file__).with_name("profile.example.yaml")
DEFAULT_AUDIT_PATH = Path("data/profile_audit.jsonl")


class ProfileStore:
    def __init__(self, path: Path = DEFAULT_PROFILE_PATH, audit_path: Path = DEFAULT_AUDIT_PATH) -> None:
        self.path = path
        self.audit_path = audit_path

    def load(self) -> dict[str, Any]:
        profile_path = self.path if self.path.exists() else EXAMPLE_PROFILE_PATH
        with profile_path.open("r", encoding="utf-8") as profile_file:
            data = yaml.safe_load(profile_file) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Profile at {profile_path} must be a YAML mapping.")
        return data

    def flattened_terms(self) -> set[str]:
        terms: set[str] = set()

        def collect(value: Any) -> None:
            if isinstance(value, dict):
                for nested in value.values():
                    collect(nested)
            elif isinstance(value, list):
                for nested in value:
                    collect(nested)
            elif isinstance(value, str):
                terms.add(value.lower())

        collect(self.load())
        return terms

    def apply_updates(
        self,
        updates: dict[str, list[str]],
        source: str = "profile_update_proposal",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        profile = self.load()
        normalized_updates = _normalize_updates(updates)
        for key, values in normalized_updates.items():
            existing = profile.get(key)
            if isinstance(existing, list):
                profile[key] = _dedupe([*existing, *values])
            elif existing is None:
                profile[key] = values
            else:
                profile[key] = _dedupe([str(existing), *values])

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as profile_file:
            yaml.safe_dump(profile, profile_file, sort_keys=False, allow_unicode=True)
        self._append_audit_record(source, normalized_updates, profile, metadata)
        return profile

    def _append_audit_record(
        self,
        source: str,
        updates: dict[str, list[str]],
        profile: dict[str, Any],
        metadata: dict[str, Any] | None,
    ) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "updates": updates,
            "profile_schema_version": 1,
            "profile_snapshot": profile,
            "metadata": metadata or {},
        }
        with self.audit_path.open("a", encoding="utf-8") as audit_file:
            audit_file.write(json.dumps(record, ensure_ascii=True) + "\n")


def _normalize_updates(updates: dict[str, list[str]]) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    for key, values in updates.items():
        clean_key = key.strip()
        clean_values = [value.strip() for value in values if value and value.strip()]
        if clean_key and clean_values:
            normalized[clean_key] = _dedupe(clean_values)
    return normalized


def _dedupe(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result
