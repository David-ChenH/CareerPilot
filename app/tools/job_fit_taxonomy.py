from enum import StrEnum


JOB_FIT_TAXONOMY_VERSION = 1


class ConcernCode(StrEnum):
    RESEARCH_MISMATCH = "research_mismatch"
    FRONTEND_HEAVY = "frontend_heavy"
    PROMPT_TOOLING_HEAVY = "prompt_tooling_heavy"
    LOW_BACKEND_OWNERSHIP = "low_backend_ownership"
    SENIORITY_MISMATCH = "seniority_mismatch"
    WEAK_PLATFORM_SCOPE = "weak_platform_scope"


class GapCode(StrEnum):
    KUBERNETES = "kubernetes"
    STREAM_PROCESSING = "stream_processing"
    DISTRIBUTED_SYSTEMS_DEPTH = "distributed_systems_depth"
    PRODUCTION_AI_EXPERIENCE = "production_ai_experience"
    CLOUD_INFRA_DEPTH = "cloud_infra_depth"


class GrowthAreaCode(StrEnum):
    ML_EVALUATION_GROWTH = "ml_evaluation_growth"
    KUBERNETES_GROWTH = "kubernetes_growth"
    STREAM_PROCESSING_GROWTH = "stream_processing_growth"
    AI_PLATFORM_DEPTH = "ai_platform_depth"


CONCERN_CODE_DESCRIPTIONS = {
    ConcernCode.RESEARCH_MISMATCH: "Role primarily requires research, publication, model science, or PhD-style research depth.",
    ConcernCode.FRONTEND_HEAVY: "Role primarily requires frontend, UI, React, or user-interface implementation.",
    ConcernCode.PROMPT_TOOLING_HEAVY: "Role centers on prompt authoring, prompt templates, labeling, prompt operations, or prompt library work.",
    ConcernCode.LOW_BACKEND_OWNERSHIP: "Role has limited backend service, platform, infrastructure, or distributed systems ownership.",
    ConcernCode.SENIORITY_MISMATCH: "Role level appears meaningfully too junior or too senior for the profile.",
    ConcernCode.WEAK_PLATFORM_SCOPE: "Role is application-only or business-logic-only with little platform/infrastructure depth.",
}

GAP_CODE_DESCRIPTIONS = {
    GapCode.KUBERNETES: "Kubernetes or container orchestration is a hard requirement and is weak or missing in the profile.",
    GapCode.STREAM_PROCESSING: "Streaming systems such as Flink, Kafka, or stream processing are hard requirements.",
    GapCode.DISTRIBUTED_SYSTEMS_DEPTH: "The role requires distributed systems depth beyond the supplied profile.",
    GapCode.PRODUCTION_AI_EXPERIENCE: "Production AI/LLM platform experience is central and weaker than required.",
    GapCode.CLOUD_INFRA_DEPTH: "Cloud infrastructure depth is central and weaker than required.",
}

GROWTH_AREA_CODE_DESCRIPTIONS = {
    GrowthAreaCode.ML_EVALUATION_GROWTH: "ML evaluation, training, experimentation, or model-quality systems are useful/preferred growth areas.",
    GrowthAreaCode.KUBERNETES_GROWTH: "Kubernetes appears useful or preferred, but not a hard blocker.",
    GrowthAreaCode.STREAM_PROCESSING_GROWTH: "Streaming systems are useful or preferred, but not hard blockers.",
    GrowthAreaCode.AI_PLATFORM_DEPTH: "Deeper AI platform or agent infrastructure knowledge would improve readiness.",
}


def taxonomy_prompt() -> str:
    return "\n".join(
        [
            f"Job fit taxonomy version: {JOB_FIT_TAXONOMY_VERSION}",
            _format_codes("Allowed concern_codes", CONCERN_CODE_DESCRIPTIONS),
            _format_codes("Allowed gap_codes", GAP_CODE_DESCRIPTIONS),
            _format_codes("Allowed growth_area_codes", GROWTH_AREA_CODE_DESCRIPTIONS),
            "Return only codes from these lists. If no code applies, return an empty list.",
            "Use codes for stable classification and natural-language fields for user-facing explanation.",
        ]
    )


def _format_codes(title: str, descriptions: dict[StrEnum, str]) -> str:
    lines = [f"{title}:"]
    for code, description in descriptions.items():
        lines.append(f"- {code.value}: {description}")
    return "\n".join(lines)
