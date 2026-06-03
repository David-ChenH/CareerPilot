import re


PROFILE_UPDATE_VERBS = ("add", "correct", "save", "update", "remember")
PROFILE_MEMORY_WORDS = ("background", "education", "profile")


def extract_profile_updates_from_message(message: str) -> dict[str, list[str]]:
    """Extract explicit profile-memory updates from a chat message."""
    if not _looks_like_profile_update(message):
        return {}

    updates: dict[str, list[str]] = {}
    education = _extract_education(message)
    if education:
        updates["education"] = education
    return updates


def _looks_like_profile_update(message: str) -> bool:
    lowered = message.lower()
    if "education background" in lowered and ("university" in lowered or re.search(r"\b\d{4}\s*-\s*\d{4}\b", message)):
        return True
    return any(verb in lowered for verb in PROFILE_UPDATE_VERBS) and any(
        word in lowered for word in PROFILE_MEMORY_WORDS
    )


def _extract_education(message: str) -> list[str]:
    if "education" not in message.lower():
        return []

    matches = [
        _clean_profile_fact(match.group(0))
        for match in re.finditer(
            r"[A-Z][A-Za-z .&'-]+ University,\s*[^,\n;]+,\s*\d{4}\s*-\s*\d{4}",
            message,
        )
    ]
    if matches:
        return _dedupe(matches)

    candidate = _after_marker(message, "education background")
    if not candidate:
        candidate = _after_marker(message, "education")
    if not candidate:
        candidate = message

    pieces = re.split(r"[;\n]+", candidate)
    return _dedupe([_clean_profile_fact(piece) for piece in pieces if _looks_like_education_fact(piece)])


def _after_marker(message: str, marker: str) -> str:
    index = message.lower().find(marker)
    if index < 0:
        return ""
    result = message[index + len(marker) :]
    return result.lstrip(" :,-")


def _looks_like_education_fact(value: str) -> bool:
    lowered = value.lower()
    return "university" in lowered or bool(re.search(r"\b\d{4}\s*-\s*\d{4}\b", value))


def _clean_profile_fact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" .:-")


def _dedupe(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result
