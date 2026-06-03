from dataclasses import dataclass


MAX_JOB_ANALYSIS_CHARS = 24_000
HEAD_CHARS = 8_000
TAIL_CHARS = 4_000
KEYWORD_WINDOW_CHARS = 3_500

JOB_SIGNAL_KEYWORDS = [
    "overview",
    "about the team",
    "team",
    "responsibilities",
    "qualifications",
    "required qualifications",
    "preferred qualifications",
    "requirements",
    "minimum qualifications",
    "benefits",
    "compensation",
]


@dataclass(frozen=True)
class CompactedText:
    text: str
    original_length: int
    compacted_length: int
    was_compacted: bool


def compact_job_text(text: str, max_chars: int = MAX_JOB_ANALYSIS_CHARS) -> CompactedText:
    normalized = _normalize_text(text)
    if len(normalized) <= max_chars:
        return CompactedText(
            text=normalized,
            original_length=len(text),
            compacted_length=len(normalized),
            was_compacted=len(normalized) != len(text),
        )

    segments = [_segment(normalized, 0, HEAD_CHARS)]
    lower_text = normalized.lower()
    for keyword in JOB_SIGNAL_KEYWORDS:
        index = lower_text.find(keyword)
        if index >= 0:
            start = max(0, index - KEYWORD_WINDOW_CHARS // 3)
            end = min(len(normalized), index + KEYWORD_WINDOW_CHARS)
            segments.append(_segment(normalized, start, end))
    segments.append(_segment(normalized, max(0, len(normalized) - TAIL_CHARS), len(normalized)))

    compacted = _join_unique_segments(segments)
    if len(compacted) > max_chars:
        compacted = compacted[: max_chars - 160].rstrip()

    note = (
        "[CareerPilot note: fetched page text was compacted before analysis because it exceeded "
        f"the local context budget. Original characters: {len(normalized)}.]\n\n"
    )
    compacted = f"{note}{compacted}"
    return CompactedText(
        text=compacted[:max_chars].rstrip(),
        original_length=len(text),
        compacted_length=min(len(compacted), max_chars),
        was_compacted=True,
    )


def _normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    useful_lines = []
    previous = None
    for line in lines:
        if not line:
            continue
        if line == previous:
            continue
        useful_lines.append(line)
        previous = line
    return "\n".join(useful_lines).strip()


def _segment(text: str, start: int, end: int) -> str:
    start = max(0, start)
    end = min(len(text), end)
    if start > 0:
        newline = text.find("\n", start)
        if 0 <= newline < end:
            start = newline + 1
    if end < len(text):
        newline = text.rfind("\n", start, end)
        if newline > start:
            end = newline
    return text[start:end].strip()


def _join_unique_segments(segments: list[str]) -> str:
    seen = set()
    unique_segments = []
    for segment in segments:
        if not segment:
            continue
        fingerprint = segment[:500]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique_segments.append(segment)
    return "\n\n[...]\n\n".join(unique_segments)
