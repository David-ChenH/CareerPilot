# Evaluation Strategy

CareerPilot uses evaluations to treat agent output quality as product behavior, not as a subjective afterthought.

The first eval harness focuses on job analysis because that is the core decision point in the product: should the user apply, skip, or prepare differently for a role?

## What The Eval Checks

The job-analysis eval runner executes representative job descriptions against a frozen eval profile:

```text
eval profile
  -> job description fixture
  -> coordinator.analyze(save=False)
  -> parser/scorer/validator/guidance output
  -> assertions on score, priority, recommendation, gaps, concerns, and extracted skills
```

The current fixtures cover:

- a strong backend/AI-platform role that should be recommended
- a research-scientist role that should be low fit for this profile
- a frontend/prompt-tooling role that should be low fit
- a backend/platform role that should not hallucinate RAG gaps
- a language-alternative role where C#, C++, or JavaScript should not become hard blockers when Java is accepted
- a Databricks-style language-alternative role where `either Java, Scala or C++` should not make C++ a barrier for a Java-capable profile
- a backend AI-platform role where preferred ML depth should be treated as a growth area, not a blocker

This gives us a regression harness for the failure modes we care about most: over-recommending weak roles, missing important gaps, and producing repeated or unsupported concerns.

The eval assertions are deterministic quality checks over generated output. They are not a replacement for semantic scoring. The model can still reason flexibly, but the product can reject known-bad output patterns such as unsupported gaps, duplicate concerns, or missing evidence.

The production analysis path also includes a bounded LLM fit validator. The validator is not a free-form chatbot; it returns a typed validation report and can trigger one repair pass for fit-only issues such as unsupported gaps, preferred-as-required mistakes, or alternative-requirement conflicts.

For semantic categories, prefer canonical labels over exact prose. For example, an LLM might describe the same concern as "frontend-heavy," "mostly UI work," or "limited backend ownership." The user-facing sentence can vary, but the structured output should use stable labels such as `frontend_heavy`, `research_mismatch`, or `prompt_tooling_heavy`. This makes tests, UI grouping, and historical analysis more reliable without forcing the model to write awkward fixed phrases.

## Commands

Run the LLM parser, scorer, and guidance generator:

```bash
careerpilot-eval --llm --json
```

Equivalent module form:

```bash
python -m app.evals.job_analysis_cli --llm --json
```

LLM evals require the `ai` extra and `OPENAI_API_KEY`:

```bash
pip install -e ".[dev,ai]"
```

## Files

```text
app/evals/job_analysis.py          Typed eval runner and assertion logic
app/evals/job_analysis_cli.py      CLI adapter
evals/profiles/backend_ai_platform.yaml
evals/job_analysis/cases.yaml
tests/test_job_analysis_evals.py   Regression coverage for the eval harness
```

The eval profile is intentionally separate from `app/memory/profile.local.yaml`. Production evals need stable inputs, otherwise profile edits can cause unrelated score drift.

## How To Add A Case

Add a case to `evals/job_analysis/cases.yaml`:

```yaml
- id: unique-case-id
  name: "Human-readable case name"
  description: "What product behavior this case protects."
  job_description: |
    Paste or synthesize a representative job description here.
  expectations:
    min_score: 70
    priority: "high"
    recommendation: "apply"
    required:
      - field: "fit.gap_codes"
        terms: ["kubernetes"]
    forbidden:
      - field: "fit.concern_codes"
        terms: ["research_mismatch"]
    no_duplicates:
      - "fit.concerns"
      - "fit.gaps"
    require_evidence:
      - field: "fit.gaps"
        terms: ["Kubernetes"]
```

Supported assertion fields include:

- `parsed.title`
- `parsed.company`
- `parsed.skills`
- `parsed.required_skills`
- `parsed.preferred_skills`
- `parsed.accepted_skill_alternatives`
- `parsed.requirements`
- `parsed.responsibilities`
- `fit.strong_matches`
- `fit.gaps`
- `fit.growth_areas`
- `fit.concerns`
- `fit.concern_codes`
- `fit.gap_codes`
- `fit.growth_area_codes`
- `fit.uncategorized_observations`
- `fit.summary`
- `fit.transition_notes`
- `guidance.apply_reasoning`
- `guidance.prep_plan`
- `guidance.resume_guidance`
- `guidance.learning_plan`
- `guidance.interview_focus`

Expectation types:

- `required`: terms that must appear in a field.
- `forbidden`: terms that must not appear in a field.
- `no_duplicates`: list fields that should not contain repeated normalized items.
- `require_evidence`: terms that require matching evidence in the corresponding evidence group.

Use `forbidden` for known hallucination regressions. Use `require_evidence` for major claims that should be grounded in the job description, such as hard skill gaps or concerns.

Use canonical code fields for category-level behavior. Use natural-language fields when the exact user-facing claim matters, such as forbidding a specific hallucinated technology in `fit.gaps`.

## Production Lessons

This structure mirrors production agent-system practice:

- Keep eval cases as data so product expectations are reviewable.
- Keep eval profiles frozen so results are reproducible.
- Run deterministic unit tests with explicit fake semantic evaluators for stable application-layer coverage.
- Run LLM evals before prompt/schema changes and compare JSON reports.
- Treat eval failures as design feedback, not just test failures.
- Convert real product mistakes into sanitized eval cases so fixes become durable.

Future improvements should add richer graded evals, model-output snapshots, cost/latency tracking, and CI modes that separate stable application-layer gates from LLM quality checks.
