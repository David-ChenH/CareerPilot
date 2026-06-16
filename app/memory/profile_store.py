from pathlib import Path
from typing import Any
import json
from datetime import datetime, timezone

import yaml

from app.memory.profile_schema import ProfileV1, load_profile_v1


DEFAULT_PROFILE_PATH = Path(__file__).with_name("profile.local.yaml")
EXAMPLE_PROFILE_PATH = Path(__file__).with_name("profile.example.yaml")
DEFAULT_AUDIT_PATH = Path("data/profile_audit.jsonl")


class ProfileStore:
    def __init__(self, path: Path = DEFAULT_PROFILE_PATH, audit_path: Path = DEFAULT_AUDIT_PATH) -> None:
        self.path = path
        self.audit_path = audit_path

    def load(self) -> dict[str, Any]:
        return self.load_model().to_runtime_context()

    def load_model(self) -> ProfileV1:
        profile_path = self.path if self.path.exists() else EXAMPLE_PROFILE_PATH
        data = self._read_profile_file(profile_path)
        if not isinstance(data, dict):
            raise ValueError(f"Profile at {profile_path} must be a YAML mapping.")
        return load_profile_v1(data)

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
        profile_model = self.load_model()
        profile = profile_model.model_dump(mode="json", exclude_none=True)
        normalized_updates = _normalize_updates(updates)
        for key, values in normalized_updates.items():
            _apply_update_to_profile(profile, key, values)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as profile_file:
            yaml.safe_dump(profile, profile_file, sort_keys=False, allow_unicode=True)
        updated = load_profile_v1(profile)
        self._append_audit_record(source, normalized_updates, updated.model_dump(mode="json", exclude_none=True), metadata)
        return updated.to_runtime_context()

    def _read_profile_file(self, path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as profile_file:
            return yaml.safe_load(profile_file) or {}

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


def _apply_update_to_profile(profile: dict[str, Any], key: str, values: list[str]) -> None:
    preferences = profile.setdefault("preferences", {})
    list_targets = {
        "core_background": profile.setdefault("background", []),
        "background": profile.setdefault("background", []),
        "experience_highlights": profile.setdefault("experience_highlights", []),
        "target_roles": preferences.setdefault("target_roles", []),
        "career_goals": preferences.setdefault("career_goals", []),
        "learning_goals": preferences.setdefault("learning_goals", []),
        "must_have": preferences.setdefault("must_have", []),
        "nice_to_have": preferences.setdefault("nice_to_have", []),
        "avoid": preferences.setdefault("avoid", []),
        "unknown_or_to_confirm": preferences.setdefault("unknown_or_to_confirm", []),
    }
    if key in {"technical_strengths", "skills"}:
        existing_names = {str(skill.get("name", "")).lower() for skill in profile.setdefault("skills", []) if isinstance(skill, dict)}
        for value in values:
            if value.lower() not in existing_names:
                profile["skills"].append({"name": value, "category": "general", "proficiency": "working"})
                existing_names.add(value.lower())
        return
    if key == "education":
        existing = {str(entry.get("raw") or entry.get("school") or "").lower() for entry in profile.setdefault("education", []) if isinstance(entry, dict)}
        for value in values:
            if value.lower() not in existing:
                profile["education"].append({"school": value, "raw": value})
                existing.add(value.lower())
        return
    if key in list_targets:
        list_targets[key][:] = _dedupe([*list_targets[key], *values])
        return
    profile[key] = _dedupe([*([str(profile[key])] if key in profile else []), *values])
