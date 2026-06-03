from pydantic import BaseModel, Field


class ExtractedSection(BaseModel):
    heading: str | None = None
    items: list[str] = Field(default_factory=list)
    source: str
    order: int


class ExtractedJobPosting(BaseModel):
    metadata: dict[str, str | None] = Field(default_factory=dict)
    sections: list[ExtractedSection] = Field(default_factory=list)
    extraction_source: str
    warnings: list[str] = Field(default_factory=list)

    def analysis_text(self, fallback_text: str) -> str:
        section_text = _sections_text(self.sections)
        if not section_text:
            return fallback_text.strip()
        metadata_text = "\n".join(
            value.strip()
            for value in self.metadata.values()
            if value and value.strip() and value.strip() not in section_text
        )
        return "\n".join(part for part in [metadata_text, section_text] if part).strip()


def sections_from_lines(text: str, source: str, headings: list[str] | None = None) -> list[ExtractedSection]:
    sections: list[ExtractedSection] = []
    heading: str | None = None
    items: list[str] = []
    dom_headings = {" ".join(value.strip().split()).rstrip(":").lower() for value in headings or [] if value.strip()}

    def append_section() -> None:
        if items:
            sections.append(
                ExtractedSection(
                    heading=heading,
                    items=list(items),
                    source=source,
                    order=len(sections),
                )
            )

    for raw_line in text.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        if line.rstrip(":").lower() in dom_headings or _looks_like_heading(line):
            append_section()
            heading = line.rstrip(":")
            items = []
            continue
        items.append(line)
    append_section()
    return sections


def _sections_text(sections: list[ExtractedSection]) -> str:
    parts = []
    for section in sections:
        if section.heading:
            parts.append(section.heading)
        parts.extend(section.items)
    return "\n".join(parts).strip()


def _looks_like_heading(line: str) -> bool:
    if len(line) > 100:
        return False
    lowered = line.lower().rstrip(":")
    known_signals = [
        "about",
        "benefits",
        "compensation",
        "description",
        "qualifications",
        "requirements",
        "responsibilities",
        "role",
        "team",
        "what you",
        "who you",
    ]
    if line.endswith(":") and len(line.split()) <= 12:
        return True
    return len(line.split()) <= 8 and any(signal in lowered for signal in known_signals)
