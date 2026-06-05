# Agent Workflow Runtime Plan

CareerPilot is the product domain. The workflow runtime is the reusable platform layer inside it.

The goal is not to build a separate toy optimizer beside the application. The goal is to evolve CareerPilot into a realistic agent-workflow system that can execute job analysis, preparation planning, resume tailoring, research, and profile updates through observable, cost-aware workflows.

## Why This Direction Fits

CareerPilot already has useful foundations:

- `AgentTask` records with persisted status, steps, artifacts, and errors.
- A background job-link ingestion workflow.
- An allow-listed assistant action registry.
- Versioned generated artifacts with model, prompt, schema, and workflow provenance.
- Explicit confirmation before profile updates.
- LLM-led semantic analysis with deterministic validation boundaries.
- A local learned-selector store that records safe declarative content-root selectors.
- Frozen job-analysis eval fixtures.

The missing layer is a reusable executor. The current background ingestion flow is written directly in `app/main.py`. It works, but each future workflow would otherwise repeat orchestration logic.

## Product Goal

Given a user goal such as:

```text
Analyze this job and create a two-week interview preparation plan.
```

CareerPilot should:

```text
resolve a workflow template
  -> build a typed task DAG
  -> validate dependencies and budget
  -> run ready tasks in dependency order
  -> run independent tasks concurrently when safe
  -> reuse cached outputs
  -> route each task to an appropriate model tier or deterministic tool
  -> retry or escalate failures according to policy
  -> evaluate outputs before downstream use
  -> pause for approval when required
  -> persist trace, cost, cache, and artifact metadata
  -> aggregate the final result
```

## Important Boundaries

1. Keep planning constrained at first.
   - Start from versioned workflow templates for supported goals.
   - Let the LLM fill typed parameters or recommend a template.
   - Do not allow arbitrary generated code or unrestricted task graphs.

2. Separate workflow infrastructure from domain tools.
   - The executor knows dependencies, retries, cache, and cost.
   - Tools know how to fetch a page, parse a job, score fit, generate a prep plan, or draft a resume.

3. Treat cache identity as part of correctness.
   - Cache keys must include input hashes and relevant versions.
   - Profile-aware outputs must include the accepted profile version.
   - LLM outputs must include workflow, prompt, model, and schema versions.

4. Keep human approval explicit.
   - External actions, profile writes, high-cost runs, and low-confidence outputs should pause for review.

5. Trace visible execution state, not hidden chain-of-thought.
   - Store task state, inputs by reference, outputs by reference, model tier, latency, cost estimate, retry reason, cache status, and evaluation result.

## Runtime Package

Add a framework-neutral package:

```text
app/workflows/
  models.py
  templates.py
  planner.py
  dag.py
  executor.py
  cache.py
  model_router.py
  cost_tracker.py
  retry_policy.py
  evaluator.py
  trace.py
  tool_registry.py
  templates/
    job_analysis.py
    interview_prep.py
```

Keep domain implementations in their existing modules:

```text
app/tools/
  job_fetcher.py
  browser_job_fetcher.py
  llm_job_parser.py
  llm_job_scorer.py
  llm_job_guidance.py
  prep_planner.py
  resume_generator.py
```

## Task Contract

The initial task model should be intentionally small:

```python
class WorkflowTask(BaseModel):
    id: str
    tool: str
    description: str
    dependencies: list[str] = []
    input: dict = {}
    status: str = "pending"
    model_tier: str | None = None
    retry_count: int = 0
    cache_key: str | None = None
    estimated_cost_usd: float = 0
    latency_ms: int | None = None
    error_type: str | None = None
    requires_approval: bool = False
```

Use immutable task definitions and keep execution results in a separate runtime-state model once the executor grows.

## First Real DAG

Migrate the existing job-link workflow first:

```text
fetch_job
  -> extract_job
  -> analyze_fit
  -> generate_guidance
  -> await_save_approval
  -> save_job
```

`save_job` should only run when explicitly requested or approved.

Then add the interview-prep workflow:

```text
analyze_job ─────────────┐
                        ├── identify_gaps ───┬── learning_plan ──────┐
load_profile ────────────┘                    ├── coding_plan ────────┼── aggregate_plan
                                             └── system_design_plan ─┘
```

The three plan branches are the first useful demonstration of parallel execution.

## Model Routing

Start with a transparent policy:

| Task kind | Initial route |
| --- | --- |
| Deterministic transforms, hashing, persistence | no model |
| Structured extraction from clean posting | cheap |
| Fit analysis and gap reasoning | standard |
| Complex planning or retry escalation | strong |
| Cache hit | no model |

Keep model names configurable. Store the selected model and routing reason in the trace.

## Cache Strategy

Implement two levels:

1. Tool-output cache
   - Key: tool name, normalized inputs, tool version.
   - Example: rendered extraction for an unchanged source URL and content hash.

2. Semantic-artifact cache
   - Key: content hash, accepted profile version when relevant, workflow version, prompt version, schema version, and model.
   - Example: reuse a prior job parse when the posting text has not changed.

Recipes and caches solve different problems:

- A learned selector observation cheaply narrows the correct DOM content root.
- A cache avoids repeating a tool or model call when the effective input is unchanged.

## Failure Policy

Represent failures explicitly:

```text
retryable_error
timeout
invalid_output
dependency_failed
budget_exceeded
approval_required
non_retryable_error
```

Initial policy:

- Retry transient tool failures once.
- Retry invalid LLM output once with clearer validation feedback.
- Escalate model tier only when policy allows.
- Block downstream tasks after permanent dependency failure.
- Pause before exceeding the workflow budget.

## Evaluation

Each task should support a lightweight evaluator:

- required fields present
- Pydantic schema valid
- output size within bounds
- expected evidence present
- dependency outputs available
- no ungrounded external action

Later add:

- LLM-as-judge evaluation for selected semantic outputs
- golden workflow traces
- cost regression thresholds
- selector-drift fixtures

## Agent Skills and Reviewed Extraction Overrides

Keep agent-facing guidance separate from reviewed site defaults and local observations:

```text
app/agent_skills/
  career_page_extraction/
    SKILL.md
    metadata.yaml

app/extraction_overrides/career_pages/
  microsoft/
    override.yaml

data/
  career_page_selectors.local.json
```

The agent skill explains the safe extraction strategy. An optional reviewed override contains typed site-specific exceptions. Local learned selector observations record which content root currently works. A future LLM may propose a declarative selector when discovery fails, but the application validates it before candidate storage and promotes it only after repeated success or review.

## Implementation Phases

### Phase 0: Agent Skills and Extraction Overrides

- Status: foundation implemented.
- Add a framework-neutral agent-skill catalog.
- Add typed reviewed extraction-override loading.
- Seed the Microsoft reviewed override from the learned local selector.
- Keep local learned observations separate from committed public examples.
- Add validation tests.

### Phase 1: Workflow Runtime Core

- Status: typed contracts, DAG validation, minimal execution, allow-listed tools, dependency-output passing, failure blocking, in-memory traces, `job_ingestion` product migration, graph artifacts, and UI trace visibility implemented.
- Add typed workflow and task models.
- Add cycle detection and topological ordering.
- Add output passing and dependency blocking.
- Add in-memory execution trace.
- Use deterministic fake tools in tests.

### Phase 2: Parallelism, Cache, and Cost

- Run independent tasks concurrently.
- Add local SQLite cache storage.
- Add deterministic cache-key generation.
- Add model-tier policy and cost estimates.
- Add workflow budget checks.

### Phase 3: Failure Handling and Evaluation

- Add typed errors and retry policy.
- Add retry escalation.
- Add task evaluators.
- Add approval pause state.
- Persist workflow-run traces and task runs.

### Phase 4: CareerPilot Integration

- Status: background job-link ingestion migrated onto the executor and exposed through UI workflow graph/trace artifacts. Link-based `Fetch & Analyze` now uses the same task path with `save=false`, so slow preview analysis shows progress and returns its final analysis artifact without writing to the tracker.
- Preserve current API and UI behavior while replacing route-owned orchestration.
- Add cost and cache-hit details to the UI after those runtime fields exist.
- Add the interview-prep DAG with parallel plan branches.

### Phase 5: Framework Comparison

- Implement a LangGraph adapter for one workflow after the framework-neutral runtime contracts are stable.
- Compare manual executor versus LangGraph for persistence, retries, interrupts, observability, and operational complexity.
- Document the tradeoff rather than adopting a framework only for novelty.

### Phase 6: Deployment Basics

- Add Dockerfile and local container workflow.
- Add a worker boundary if background execution outgrows FastAPI `BackgroundTasks`.
- Add Kubernetes manifests only after the local runtime has meaningful workload behavior to deploy.

## Recommended Next Implementation

The next implementation should use the visible runtime foundation for a richer domain workflow:

1. Add the interview-prep workflow template with parallel planning branches.
2. Add a first cache-key contract for reusable workflow outputs.
3. Add model-tier routing and estimated cost reporting.
4. Add persistent workflow traces after the in-memory trace shape stabilizes.

Do not add SQLite cache tables, LangGraph, or new UI in this next slice.

## Interview Explanation

> I started from a real product workflow rather than a synthetic agent demo. CareerPilot already had persistent tasks, typed LLM outputs, versioned artifacts, approvals, and evaluation fixtures. I extracted a framework-neutral DAG runtime so workflows could gain dependency-aware execution, cache reuse, model routing, budget controls, retries, and traceability. I kept domain tools separate from orchestration and used LangGraph later as an adapter comparison after the runtime contracts were clear.
