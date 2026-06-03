import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_ANALYSIS_FEEDBACK_PATH = Path("data/analysis_feedback.jsonl")


def record_analysis_feedback(
    feedback_type: str,
    note: str | None,
    analysis: dict[str, Any],
    source_url: str | None = None,
    path: Path = DEFAULT_ANALYSIS_FEEDBACK_PATH,
) -> dict[str, Any]:
    record = {
        "id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feedback_type": feedback_type,
        "note": note,
        "source_url": source_url,
        "job_title": (analysis.get("parsed_job") or {}).get("title"),
        "company": (analysis.get("parsed_job") or {}).get("company"),
        "recommendation": (analysis.get("fit") or {}).get("recommendation"),
        "priority": (analysis.get("fit") or {}).get("priority"),
        "score": (analysis.get("fit") or {}).get("score"),
        "analysis": analysis,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as feedback_file:
        feedback_file.write(json.dumps(record, ensure_ascii=True) + "\n")
    return record
