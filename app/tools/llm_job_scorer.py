import json
import os
import re
from typing import Any

from pydantic import BaseModel, Field

from app.config.env import load_local_env
from app.tools.job_fit_taxonomy import ConcernCode, GapCode, GrowthAreaCode, taxonomy_prompt
from app.tools.job_parser import ParsedJob
from app.tools.scoring import EvidenceItem, JobFit


DEFAULT_LLM_MODEL = "gpt-4o-mini"


class LLMFitEvidence(BaseModel):
    claim: str = Field(description="The exact match, gap, concern, or recommendation claim.")
    evidence_from_job: str = Field(description="Short quote or close paraphrase from parsed_job that supports the claim.")
    profile_signal: str | None = Field(default=None, description="Profile fact that explains why this is a match, gap, or concern.")
    profile_source_path: str | None = Field(
        default=None,
        description=(
            "YAML-like profile path for a positive profile fact, such as "
            "technical_strengths[0] or experience_highlights[3]. Leave null for absence claims."
        ),
    )
    severity: str | None = Field(default=None, description="One of: critical, useful, nice-to-have, blocker, positive.")
    confidence: str = Field(description="One of: high, medium, low.")


class LLMSemanticJobFit(BaseModel):
    final_score: int = Field(description="Overall fit score from 0 to 100.")
    priority: str = Field(description="One of: high, medium, low.")
    role_alignment_score: int = Field(description="Role alignment from 0 to 10.")
    skill_match_score: int = Field(description="Current skill match from 0 to 10.")
    career_transition_score: int = Field(description="How useful this role is for the user's career transition from 0 to 10.")
    seniority_fit_score: int = Field(description="Seniority fit from 0 to 10.")
    learning_roi_score: int = Field(description="Learning return on investment from 0 to 10.")
    strong_matches: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    growth_areas: list[str] = Field(
        default_factory=list,
        description="Useful preparation areas that are preferred, optional, or worth validating, but are not missing hard requirements.",
    )
    missing_or_risky_skills: list[str] = Field(
        default_factory=list,
        description="Skills or technologies that are important for the role and weak/missing in the profile.",
    )
    concerns: list[str] = Field(default_factory=list)
    concern_codes: list[ConcernCode] = Field(default_factory=list)
    gap_codes: list[GapCode] = Field(default_factory=list)
    growth_area_codes: list[GrowthAreaCode] = Field(default_factory=list)
    uncategorized_observations: list[str] = Field(default_factory=list)
    transition_notes: list[str] = Field(default_factory=list)
    recommendation: str = Field(description="One of: apply, consider, skip.")
    summary: str
    match_evidence: list[LLMFitEvidence] = Field(default_factory=list)
    gap_evidence: list[LLMFitEvidence] = Field(default_factory=list)
    concern_evidence: list[LLMFitEvidence] = Field(default_factory=list)
    recommendation_evidence: list[LLMFitEvidence] = Field(default_factory=list)


class LLMJobScorerUnavailable(RuntimeError):
    pass


def score_job_fit_with_llm(
    profile: dict[str, Any],
    job: ParsedJob,
) -> JobFit:
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMJobScorerUnavailable("OPENAI_API_KEY is not set.")

    try:
        from openai import OpenAI
    except ImportError as error:
        raise LLMJobScorerUnavailable(
            'OpenAI SDK is not installed. Install it with `pip install -e ".[dev,ai]"`.'
        ) from error

    client = OpenAI(api_key=api_key)
    model = os.getenv("JOB_AGENT_LLM_MODEL", DEFAULT_LLM_MODEL)

    try:
        response = client.responses.parse(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Evaluate job fit for a user who may be making a career transition. "
                        "Use the profile, target roles, preferences, avoid-list, and parsed job facts. "
                        "Identify missing or risky skills semantically from the job requirements and user profile; "
                        "do not rely on predefined skill lists. "
                        "Reward roles that are realistic bridges toward the user's stated direction, "
                        "not only roles that perfectly match current skills. Penalize roles that are "
                        "misaligned, too research-heavy, too frontend-heavy, too junior, or mostly unrelated. "
                        "Use only the supplied profile and job text; do not assume facts that are not provided. "
                        "Every gap and concern must be grounded in a skill, requirement, responsibility, or role signal "
                        "that appears in parsed_job. Do not add generic prep topics such as Docker, Kubernetes, or RAG "
                        "unless they are present in parsed_job. If a role lists Java as an accepted qualification, do not "
                        "describe the role as mainly C++, C#, or Scala unless the job text clearly emphasizes only those languages. "
                        "A list such as Java, Scala, or C++ is an alternatives list: satisfying one accepted "
                        "language is enough unless the posting explicitly requires a particular language elsewhere. "
                        "Put preferred, optional, or useful-to-validate capabilities in growth_areas, not gaps. Reserve "
                        "gaps for missing hard requirements or capabilities clearly central to the core responsibilities. "
                        "Treat parsed_job.ambiguous_qualifications as facts to validate, not as hard requirements or blockers. "
                        "Do not guess whether a flattened qualification statement was required or preferred. "
                        "Do not repeat the same concept with slightly different wording across gaps, growth_areas, or concerns. "
                        f"{taxonomy_prompt()} "
                        "For each important match, gap, concern, and recommendation, include evidence. Evidence must quote "
                        "or closely paraphrase parsed_job and include a profile signal when the claim compares against the user. "
                        "When profile_signal cites a positive profile fact, include a profile_source_path using the supplied "
                        "profile keys and array indexes when possible, for example technical_strengths[1] or "
                        "experience_highlights[4]. For absence claims like 'C++ is not listed in the profile', leave "
                        "profile_source_path null."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "profile": profile,
                            "parsed_job": job.model_dump(),
                            "rubric": {
                                "role_alignment_score": "Does this role match the user's target direction?",
                                "skill_match_score": "How much does the role match current strengths?",
                                "career_transition_score": "Would this role help the user move toward their target identity?",
                                "seniority_fit_score": "Is the level realistic for the user?",
                                "learning_roi_score": "Are the gaps valuable and learnable rather than disqualifying?",
                            },
                        },
                        ensure_ascii=True,
                    ),
                },
            ],
            text_format=LLMSemanticJobFit,
        )
    except Exception as error:
        raise LLMJobScorerUnavailable(f"LLM scorer request failed: {error}") from error

    llm_fit = response.output_parsed
    if llm_fit is None:
        raise LLMJobScorerUnavailable("LLM scorer returned no structured output.")

    score = max(0, min(llm_fit.final_score, 100))
    priority = _normalize_priority(llm_fit.priority, score)
    grounded_gaps = _filter_grounded_items(
        _merge_unique(llm_fit.gaps, llm_fit.missing_or_risky_skills),
        job,
        profile=profile,
    )
    grounded_growth_areas = _filter_grounded_items(llm_fit.growth_areas, job, profile=profile)
    hard_gaps, downgraded_growth_areas = _partition_hard_gaps(grounded_gaps, job)
    final_growth_areas = _merge_unique(
        _merge_unique(grounded_growth_areas, downgraded_growth_areas),
        _implicit_growth_areas(job=job, hard_gaps=hard_gaps),
    )
    evidence = {
        "strong_matches": _ground_evidence(llm_fit.match_evidence, job, profile, allowed_claims=None),
        "gaps": _ground_evidence(llm_fit.gap_evidence, job, profile, allowed_claims=hard_gaps),
        "concerns": _ground_evidence(llm_fit.concern_evidence, job, profile, allowed_claims=llm_fit.concerns),
        "recommendation": _ground_evidence(llm_fit.recommendation_evidence, job, profile, allowed_claims=None),
    }

    return JobFit(
        score=score,
        priority=priority,
        strong_matches=llm_fit.strong_matches,
        gaps=hard_gaps,
        growth_areas=final_growth_areas,
        concerns=llm_fit.concerns,
        concern_codes=_infer_concern_codes(llm_fit.concern_codes, llm_fit.concerns, job),
        gap_codes=_filter_gap_codes(llm_fit.gap_codes, hard_gaps, job),
        growth_area_codes=_infer_growth_area_codes(llm_fit.growth_area_codes, final_growth_areas, job),
        uncategorized_observations=llm_fit.uncategorized_observations,
        summary=_reconcile_summary(llm_fit.summary, hard_gaps, downgraded_growth_areas),
        score_components={
            "role_alignment": _clamp_component(llm_fit.role_alignment_score),
            "skill_match": _clamp_component(llm_fit.skill_match_score),
            "career_transition": _clamp_component(llm_fit.career_transition_score),
            "seniority_fit": _clamp_component(llm_fit.seniority_fit_score),
            "learning_roi": _clamp_component(llm_fit.learning_roi_score),
        },
        recommendation=_normalize_recommendation(llm_fit.recommendation, priority),
        transition_notes=llm_fit.transition_notes,
        evidence=evidence,
    )


def _infer_concern_codes(codes: list[ConcernCode], concerns: list[str], job: ParsedJob) -> list[ConcernCode]:
    inferred = list(dict.fromkeys(codes))
    concern_text = " ".join(concerns).lower()
    job_text = _job_evidence_text(job)
    code_signals = {
        ConcernCode.RESEARCH_MISMATCH: ["research", "publication", "phd", "model architecture", "training research"],
        ConcernCode.FRONTEND_HEAVY: ["frontend", "front-end", "react", "ui development", "user interface"],
        ConcernCode.PROMPT_TOOLING_HEAVY: [
            "prompt",
            "prompt template",
            "prompt tooling",
            "prompt-tooling",
            "prompt engineering",
            "prompt-engineering",
            "prompt library",
            "labeling",
            "data labeling",
        ],
        ConcernCode.LOW_BACKEND_OWNERSHIP: ["backend infrastructure ownership is limited", "backend ownership is limited"],
        ConcernCode.WEAK_PLATFORM_SCOPE: ["application-only", "business application"],
    }
    for code, signals in code_signals.items():
        if code not in inferred and any(signal in concern_text for signal in signals):
            inferred.append(code)
    if (
        ConcernCode.PROMPT_TOOLING_HEAVY not in inferred
        and "prompt" in job_text
        and any(signal in job_text for signal in ["prompt template", "prompt library", "labeling", "prompt engineer"])
        and any(signal in job_text for signal in ["frontend", "limited backend", "backend infrastructure ownership is limited"])
    ):
        inferred.append(ConcernCode.PROMPT_TOOLING_HEAVY)
    return inferred


def _filter_gap_codes(codes: list[GapCode], gaps: list[str], job: ParsedJob) -> list[GapCode]:
    if not gaps:
        return []
    evidence = _job_evidence_text(job)
    gap_text = " ".join(gaps).lower()
    return [
        code
        for code in dict.fromkeys(codes)
        if _code_has_support(code.value, gap_text, evidence)
    ]


def _infer_growth_area_codes(codes: list[GrowthAreaCode], growth_areas: list[str], job: ParsedJob) -> list[GrowthAreaCode]:
    evidence = _job_evidence_text(job)
    growth_text = " ".join(growth_areas).lower()
    inferred = [
        code
        for code in dict.fromkeys(codes)
        if _code_has_support(code.value, growth_text, evidence)
    ]
    if GrowthAreaCode.ML_EVALUATION_GROWTH not in inferred and _has_optional_ml_growth_signal(job):
        inferred.append(GrowthAreaCode.ML_EVALUATION_GROWTH)
    return inferred


def _code_has_support(code: str, claim_text: str, evidence: str) -> bool:
    code_aliases = {
        "kubernetes": ["kubernetes", "k8s"],
        "kubernetes_growth": ["kubernetes", "k8s"],
        "stream_processing": ["stream", "streaming", "flink", "kafka"],
        "stream_processing_growth": ["stream", "streaming", "flink", "kafka"],
        "ml_evaluation_growth": ["ml evaluation", "model training", "experimentation", "training workflows"],
        "distributed_systems_depth": ["distributed systems"],
        "production_ai_experience": ["ai platform", "llm", "agent"],
        "ai_platform_depth": ["ai platform", "llm", "agent"],
        "cloud_infra_depth": ["cloud", "infrastructure"],
    }
    aliases = code_aliases.get(code, [code.replace("_", " ")])
    return any(alias in claim_text or alias in evidence for alias in aliases)


def _implicit_growth_areas(job: ParsedJob, hard_gaps: list[str]) -> list[str]:
    growth_areas = []
    hard_gap_text = " ".join(hard_gaps).lower()
    if _has_optional_ml_growth_signal(job) and "ml evaluation" not in hard_gap_text and "model training" not in hard_gap_text:
        growth_areas.append("ML evaluation and model-training workflow familiarity")
    if _optional_signal_for_item("kubernetes", job) and "kubernetes" not in hard_gap_text:
        growth_areas.append("Kubernetes/container orchestration exposure")
    return growth_areas


def _has_optional_ml_growth_signal(job: ParsedJob) -> bool:
    optional_text = _optional_job_evidence_text(job)
    aliases = ["ml evaluation", "model evaluation", "model training", "training workflows", "experimentation"]
    return any(alias in optional_text for alias in aliases)


def _optional_job_evidence_text(job: ParsedJob) -> str:
    explicit_optional_text = " ".join([*job.preferred_skills, *job.preferred_qualifications]).lower()
    if explicit_optional_text:
        return explicit_optional_text

    description = job.description.lower()
    optional_windows = []
    for marker in ["preferred", "nice to have", "familiarity", "useful", "helpful"]:
        for match in re.finditer(re.escape(marker), description):
            optional_windows.append(description[match.start() : match.start() + 500])
    return " ".join(optional_windows)


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    merged: dict[str, str] = {}
    for value in [*first, *second]:
        cleaned = value.strip()
        if cleaned:
            merged[cleaned.lower()] = cleaned
    return list(merged.values())


def _filter_grounded_items(
    items: list[str],
    job: ParsedJob,
    profile: dict[str, Any],
) -> list[str]:
    evidence = _job_evidence_text(job)
    profile_text = json.dumps(profile, ensure_ascii=True).lower()
    grounded = []
    for item in items:
        lowered = item.lower()
        if _is_profile_known(lowered, profile_text):
            continue
        if _alternative_requirement_is_satisfied(lowered, job, profile_text):
            continue
        if _has_job_evidence(lowered, evidence):
            grounded.append(item)
    return grounded


def _partition_hard_gaps(items: list[str], job: ParsedJob) -> tuple[list[str], list[str]]:
    hard_gaps = []
    growth_areas = []
    for item in items:
        if _is_hard_requirement(item, job):
            hard_gaps.append(item)
        else:
            growth_areas.append(item)
    return hard_gaps, growth_areas


def _alternative_requirement_is_satisfied(item: str, job: ParsedJob, profile_text: str) -> bool:
    item_terms = _language_terms(item)
    if not item_terms:
        return False
    for alternatives in _language_alternative_groups(job):
        if item_terms.intersection(alternatives) and any(language in profile_text for language in alternatives):
            return True
    return False


def _language_alternative_groups(job: ParsedJob) -> list[set[str]]:
    text = " ".join(
        [job.description, *job.requirements, *job.required_skills, *job.accepted_skill_alternatives]
    ).lower()
    groups = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        languages = _language_terms(sentence)
        if len(languages) >= 2 and _looks_like_alternative_language_requirement(sentence):
            groups.append(languages)
    return groups


def _looks_like_alternative_language_requirement(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in [
            " or ",
            "either",
            "one or more",
            "including",
            "such as",
        ]
    )


def _language_terms(text: str) -> set[str]:
    lowered = text.lower()
    return {
        language
        for language, pattern in {
            "c": r"(?<![a-z0-9+#])c(?![a-z0-9+#])",
            "c++": r"c\+\+",
            "c#": r"c#|c sharp|csharp",
            "java": r"(?<![a-z0-9])java(?![a-z0-9])",
            "python": r"(?<![a-z0-9])python(?![a-z0-9])",
            "scala": r"(?<![a-z0-9])scala(?![a-z0-9])",
        }.items()
        if re.search(pattern, lowered)
    }


def _is_hard_requirement(item: str, job: ParsedJob) -> bool:
    lowered = item.lower()
    hard_skills_text = " ".join(job.required_skills).lower()
    requirements_text = " ".join(job.requirements).lower()
    preferred_text = " ".join([*job.preferred_skills, *job.preferred_qualifications]).lower()
    ambiguous_text = " ".join(job.ambiguous_qualifications).lower()
    if _has_job_evidence(lowered, ambiguous_text):
        return False
    if _optional_signal_for_item(lowered, job):
        return False
    if _has_job_evidence(lowered, hard_skills_text):
        return True
    if _has_job_evidence(lowered, preferred_text):
        return False
    if _has_job_evidence(lowered, requirements_text) and _contains_explicit_requirement_marker(lowered, requirements_text):
        return True
    return False


def _optional_signal_for_item(item: str, job: ParsedJob) -> bool:
    optional_text = _optional_job_evidence_text(job)
    return _has_job_evidence(item, optional_text)


def _contains_explicit_requirement_marker(item: str, text: str) -> bool:
    markers = ["required", "must have", "minimum qualification", "minimum requirement"]
    terms = [term for term in item.replace("/", " ").replace("-", " ").split() if len(term) >= 4]
    for term in terms[:5]:
        index = text.find(term)
        if index >= 0:
            window = text[max(0, index - 120) : index + 120]
            if any(marker in window for marker in markers):
                return True
    return False


def _reconcile_summary(summary: str, hard_gaps: list[str], downgraded_growth_areas: list[str]) -> str:
    if not downgraded_growth_areas:
        return summary
    without_gap_sentences = " ".join(
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", summary)
        if " gap" not in sentence.lower()
    ).strip()
    validation = (
        f"Validated hard gaps: {', '.join(hard_gaps)}."
        if hard_gaps
        else "No missing hard requirements were identified after validating qualification strength and accepted alternatives."
    )
    growth = f"Useful growth areas to validate: {', '.join(downgraded_growth_areas)}."
    return " ".join(part for part in [without_gap_sentences, validation, growth] if part)


def _ground_evidence(
    items: list[LLMFitEvidence],
    job: ParsedJob,
    profile: dict[str, Any],
    allowed_claims: list[str] | None,
) -> list[EvidenceItem]:
    evidence_text = _job_evidence_text(job)
    profile_facts = _flatten_profile_facts(profile)
    grounded = []
    for item in items:
        clean_claim = item.claim.strip()
        if not clean_claim or not item.evidence_from_job.strip():
            continue
        if allowed_claims is not None and not _claim_is_allowed(clean_claim, allowed_claims):
            continue
        if not _evidence_statement_is_supported(clean_claim, item.evidence_from_job, evidence_text):
            continue
        confidence = item.confidence
        profile_source_path = item.profile_source_path.strip() if item.profile_source_path else None
        profile_evidence = None
        if item.profile_signal:
            supported, inferred_path, inferred_evidence = _profile_signal_support(
                profile_signal=item.profile_signal,
                requested_path=profile_source_path,
                profile_facts=profile_facts,
            )
            if not supported:
                confidence = "low"
            else:
                profile_source_path = inferred_path or profile_source_path
                profile_evidence = inferred_evidence
        else:
            confidence = item.confidence
        grounded.append(
            EvidenceItem(
                claim=clean_claim,
                evidence_from_job=item.evidence_from_job.strip(),
                profile_signal=item.profile_signal.strip() if item.profile_signal else None,
                profile_source_path=profile_source_path,
                profile_evidence=profile_evidence,
                severity=_normalize_evidence_severity(item.severity, clean_claim, evidence_text),
                confidence=confidence,
                source="llm",
            )
        )
    return grounded


def _claim_is_allowed(claim: str, allowed_claims: list[str]) -> bool:
    lowered_claim = claim.lower()
    return any(lowered_claim in allowed.lower() or allowed.lower() in lowered_claim for allowed in allowed_claims)


def _profile_signal_is_supported(profile_signal: str, profile_facts: list[tuple[str, str]]) -> bool:
    supported, _, _ = _profile_signal_support(
        profile_signal=profile_signal,
        requested_path=None,
        profile_facts=profile_facts,
    )
    return supported


def _profile_signal_support(
    profile_signal: str,
    requested_path: str | None,
    profile_facts: list[tuple[str, str]],
) -> tuple[bool, str | None, str | None]:
    lowered_signal = profile_signal.lower()
    if any(marker in lowered_signal for marker in ["not listed", "not in the profile", "missing", "lacks", "no evidence"]):
        return True, None, None
    if requested_path:
        for path, value in profile_facts:
            if path == requested_path and _profile_signal_matches_fact(profile_signal, value):
                return True, path, value
    best_path = None
    best_value = None
    best_score = 0
    for path, value in profile_facts:
        score = _profile_fact_overlap_score(profile_signal, value)
        if score > best_score:
            best_score = score
            best_path = path
            best_value = value
    if best_score > 0:
        return True, best_path, best_value
    return False, None, None


def _profile_signal_matches_fact(profile_signal: str, fact_value: str) -> bool:
    return _profile_fact_overlap_score(profile_signal, fact_value) > 0


def _profile_fact_overlap_score(profile_signal: str, fact_value: str) -> int:
    terms = [
        term
        for term in re.split(r"[^a-z0-9#+]+", profile_signal.lower())
        if len(term) >= 4 and term not in {"with", "experience", "profile", "listed", "background", "current"}
    ]
    fact_text = fact_value.lower()
    return sum(term in fact_text for term in terms[:8])


def _flatten_profile_facts(profile: dict[str, Any]) -> list[tuple[str, str]]:
    facts: list[tuple[str, str]] = []

    def collect(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                nested_path = f"{path}.{key}" if path else str(key)
                collect(nested, nested_path)
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                collect(nested, f"{path}[{index}]")
        elif isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                facts.append((path, cleaned))
        elif value is not None:
            facts.append((path, str(value)))

    collect(profile, "")
    return facts


def _job_evidence_text(job: ParsedJob) -> str:
    return " ".join(
        [
            job.title or "",
            job.description,
            " ".join(job.skills),
            " ".join(job.required_skills),
            " ".join(job.preferred_skills),
            " ".join(job.accepted_skill_alternatives),
            " ".join(job.requirements),
            " ".join(job.preferred_qualifications),
            " ".join(job.ambiguous_qualifications),
            " ".join(job.responsibilities),
            " ".join(job.role_focus),
        ]
    ).lower()


def _has_job_evidence(item: str, evidence: str) -> bool:
    aliases = {
        "docker": ["docker", "containerized", "containerization", "containers"],
        "container": ["docker", "containerized", "containerization", "containers"],
        "kubernetes": ["kubernetes", "k8s"],
        "eks": ["eks", "elastic kubernetes service"],
        "flink": ["flink", "apache flink"],
        "rag": ["rag", "retrieval augmented generation", "retrieval-augmented generation"],
        "java": ["java"],
        "javascript": ["javascript"],
        "c++": ["c++"],
        "c#": ["c#", "c sharp"],
    }
    for key, values in aliases.items():
        if key in item:
            return any(value in evidence for value in values)
    meaningful_terms = [
        term
        for term in item.replace("/", " ").replace("-", " ").split()
        if len(term) >= 4 and term not in {"with", "role", "skill", "skills", "experience", "depth", "lack", "missing"}
    ]
    return any(term in evidence for term in meaningful_terms[:4])


def _evidence_statement_is_supported(claim: str, statement: str, job_evidence: str) -> bool:
    combined = f"{claim} {statement}".lower()
    technology_aliases = {
        "docker": ["docker", "containerized", "containerization", "containers"],
        "kubernetes": ["kubernetes", "k8s"],
        "eks": ["eks", "elastic kubernetes service"],
        "flink": ["flink", "apache flink"],
        "rag": ["rag", "retrieval augmented generation", "retrieval-augmented generation"],
        "java": ["java"],
        "javascript": ["javascript"],
        "typescript": ["typescript"],
        "c++": ["c++"],
        "c#": ["c#", "c sharp", "csharp"],
    }
    mentioned_technologies = [
        values
        for key, values in technology_aliases.items()
        if any(alias in combined for alias in [key, *values])
    ]
    if mentioned_technologies and not all(any(alias in job_evidence for alias in values) for values in mentioned_technologies):
        return False

    statement_terms = [
        term
        for term in statement.lower().replace("/", " ").replace("-", " ").split()
        if len(term) >= 5 and term not in {"requires", "required", "proficiency", "experience", "skills", "user's"}
    ]
    return _has_job_evidence(combined, job_evidence) and (
        not statement_terms or sum(term in job_evidence for term in statement_terms[:6]) >= min(2, len(statement_terms))
    )


def _normalize_evidence_severity(severity: str | None, claim: str, job_evidence: str) -> str | None:
    if not severity:
        return None
    normalized = severity.strip().lower()
    if normalized != "blocker":
        return normalized
    if _explicit_requirement_supported(claim, job_evidence):
        return "blocker"
    return "useful"


def _explicit_requirement_supported(claim: str, job_evidence: str) -> bool:
    claim_terms = [
        term
        for term in claim.lower().replace("/", " ").replace("-", " ").split()
        if len(term) >= 4 and term not in {"role", "skill", "skills", "gap", "missing", "depth"}
    ]
    requirement_markers = ["required", "must have", "minimum qualification", "proficiency"]
    for term in claim_terms[:5]:
        index = job_evidence.find(term)
        if index < 0:
            continue
        window = job_evidence[max(0, index - 160) : index + 160]
        if any(marker in window for marker in requirement_markers):
            return True
    return False


def _is_profile_known(item: str, profile_text: str) -> bool:
    known_aliases = {
        "java": ["java"],
        "python": ["python"],
        "aws": ["aws", "amazon web services"],
        "backend": ["backend"],
        "distributed": ["distributed"],
        "workflow": ["workflow", "step functions"],
    }
    return any(key in item and any(alias in profile_text for alias in aliases) for key, aliases in known_aliases.items())


def _clamp_component(value: int) -> int:
    return max(0, min(value, 10))


def _normalize_priority(priority: str, score: int) -> str:
    lowered = priority.lower().strip()
    if score < 50:
        return "low"
    if score >= 85:
        return "high"
    if score < 75 and lowered == "high":
        return "medium"
    if lowered in {"high", "medium", "low"}:
        return lowered
    if score >= 80:
        return "high"
    if score >= 65:
        return "medium"
    return "low"


def _normalize_recommendation(recommendation: str, priority: str) -> str:
    lowered = recommendation.lower().strip()
    if lowered in {"apply", "consider", "skip"}:
        return lowered
    return {"high": "apply", "medium": "consider"}.get(priority, "skip")
