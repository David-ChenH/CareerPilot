# Roadmap

CareerPilot is a local-first AI career workbench and a backend/AI-platform learning project. The roadmap prioritizes production agentic-system skills: controlled tools, typed workflows, durable memory, evaluation, observability, and cost-aware execution.

## Current State

| Area | Status | Notes |
| --- | --- | --- |
| Local app foundation | Complete | FastAPI backend, React workbench, SQLite persistence, local profile memory. |
| Single-job analysis | Complete foundation | URL/paste analysis, LLM structured extraction, required semantic scoring, guidance, evidence, canonical fit labels. |
| Application tracker | Complete foundation | Save, delete, status updates, analysis history, review-first refresh. |
| Chat | Complete foundation | Global and job-scoped chat, local history, optional web search mode. |
| Profile and resume portal | Complete foundation | Resume upload/paste proposals, explicit profile save flow, audit records. |
| Prep plans and resume drafts | Complete foundation | LLM-assisted prep plans and PDF resume generation exist; workflow integration can deepen. |
| Workflow runtime | In progress | Minimal DAG executor and job-ingestion workflow are implemented. Cost, cache, retries, and persisted traces are next. |
| Evaluation | In progress | Job-analysis eval harness exists; broader eval cases and artifact evals are next. |
| Target-company discovery | Deferred | Keep scan/cron features until single-job quality and workflow runtime are stronger. |

## Next Priorities

1. Expand analysis-quality evaluation.
   - Add more real-world eval cases from saved job mistakes.
   - Track model, prompt version, schema version, and eval output snapshots.
   - Add eval cases for resume guidance and prep-plan quality.

2. Strengthen the workflow runtime.
   - Add cache keys for reusable intermediate outputs.
   - Add model routing and cost accounting.
   - Add retry and failure policies.
   - Persist workflow traces beyond the current `AgentTask` artifacts.

3. Convert prep planning into a richer workflow DAG.
   - Analyze job and profile.
   - Identify gaps.
   - Generate learning, coding, and system-design branches.
   - Aggregate into a final plan.

4. Improve chat as an action surface.
   - Let chat invoke approved workflow tools.
   - Preserve context switching between global, job, profile, prep-plan, and resume scopes.
   - Keep memory updates explicit and reviewable.

5. Improve public demo quality.
   - Keep UI polished enough for GitHub demos.
   - Keep backend architecture as the main portfolio story.

## Deferred Work

- Broad target-company scans and cron jobs.
- Cloud deployment.
- Postgres or vector-store migration.
- LangGraph adapter.
- Multi-user auth.

These are valuable, but they should follow stronger single-job quality, workflow observability, and evaluation.

## Decision Log

### SQL First

SQLite is the right local persistence layer for this stage because the app has relational state: jobs, statuses, analysis versions, chat sessions, prep plans, resume versions, and profile proposals. A future hosted version can move behind repository interfaces to Postgres.

### Required LLM Semantic Scoring

Career-transition fit is semantic. The app should not manufacture user-facing recommendations from keyword scoring when the LLM scorer is unavailable. Deterministic code is still useful for parsing normalization, evidence validation, schema migration, and stable eval checks.

### Canonical Labels For LLM Output

Natural-language LLM explanations are useful for users but brittle for product contracts. CareerPilot stores canonical concern, gap, and growth-area labels for tests, UI grouping, and historical analysis while preserving flexible prose for explanations.

### Review-First Saved Analysis Updates

Regeneration creates a candidate analysis. The user explicitly applies it to a saved job. This preserves application status, keeps historical versions, and avoids silent destructive updates.

### Target Companies Before Open-Web Discovery

The user’s job search is focused on large target companies. A curated watchlist is more useful and reliable than scraping the whole internet. Scheduled discovery should wait until manual ingestion is reliable.

### LangGraph Later

The project should first implement one or two workflows manually to learn the runtime responsibilities: DAG validation, dependency output passing, failure blocking, trace events, cache identity, cost policy, and approvals. LangGraph can then be introduced as an adapter or replacement for scheduling mechanics.

## How To Use This Roadmap

- Use this file for project status and next-step planning.
- Use [Architecture](architecture.md) for what exists now.
- Use [Workflow Runtime](workflow_runtime.md) for the agentic-runtime transition.
- Use [Learning Guide](learning_guide.md) for concepts and interview learning.
