# Evaluation Strategy

CareerPilot uses evaluations to treat agent output quality as product behavior, not as a subjective afterthought.

The first eval harness focuses on job analysis because that is the core decision point in the product: should the user apply, skip, or prepare differently for a role?

## What The Eval Checks

The job-analysis eval runner executes representative job descriptions against a frozen eval profile:

```text
eval profile
  -> job description fixture
  -> coordinator.analyze(save=False)
  -> parser/scorer/guidance output
  -> assertions on score, priority, recommendation, gaps, concerns, and extracted skills
```

The current fixtures cover:

- a strong backend/AI-platform role that should be recommended
- a research-scientist role that should be low fit for this profile
- a frontend/prompt-tooling role that should be low fit

This gives us a regression harness for the failure modes we care about most: over-recommending weak roles, missing important gaps, and producing repeated or unsupported concerns.

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
      - field: "fit.gaps"
        terms: ["Kubernetes"]
    forbidden:
      - field: "fit.concerns"
        terms: ["research-oriented"]
```

Supported assertion fields include:

- `parsed.title`
- `parsed.company`
- `parsed.skills`
- `fit.strong_matches`
- `fit.gaps`
- `fit.concerns`
- `fit.summary`
- `fit.transition_notes`
- `guidance.apply_reasoning`
- `guidance.prep_plan`
- `guidance.resume_guidance`
- `guidance.learning_plan`
- `guidance.interview_focus`

## Production Lessons

This structure mirrors production agent-system practice:

- Keep eval cases as data so product expectations are reviewable.
- Keep eval profiles frozen so results are reproducible.
- Run deterministic unit tests with explicit fake semantic evaluators for stable application-layer coverage.
- Run LLM evals before prompt/schema changes and compare JSON reports.
- Treat eval failures as design feedback, not just test failures.

Future improvements should add richer graded evals, model-output snapshots, cost/latency tracking, and CI modes that separate stable application-layer gates from LLM quality checks.
