# Roadmap

CareerPilot is a local-first AI career workbench and a backend/AI-platform learning project. The roadmap prioritizes production agentic-system skills: controlled tools, typed workflows, durable memory, evaluation, observability, and cost-aware execution.

The target portfolio story is:

> I built CareerPilot as a production-style agentic workflow system. It started as a career assistant, but the real engineering focus is workflow orchestration, tool boundaries, memory, evaluation, traceability, and later cloud-native deployment.

## Current State

| Area | Status | Notes |
| --- | --- | --- |
| Local app foundation | Complete | FastAPI backend, React workbench, SQLite persistence, local profile memory. |
| Single-job analysis | Complete foundation | URL/paste analysis, LLM structured extraction, required semantic scoring, guidance, evidence, canonical fit labels. |
| Application tracker | Complete foundation | Save, delete, status updates, analysis history, review-first refresh. |
| Chat | In progress | Global and job-scoped chat, local history, optional web search mode, LLM planner contracts for chat-invoked actions. |
| Profile and resume portal | Complete foundation | Resume upload/paste proposals, explicit profile save flow, audit records. |
| Prep plans and resume drafts | In progress | Prep plans now run through the workflow executor with trace/evaluation artifacts; resume generation remains direct. |
| Workflow runtime | In progress | Minimal DAG executor remains the native baseline; prep-plan workflows now prefer LangGraph when installed and record runtime metadata. |
| Evaluation | In progress | Job-analysis eval harness exists; broader eval cases and artifact evals are next. |
| Target-company discovery | Deferred | Keep scan/cron features until single-job quality and workflow runtime are stronger. |

## Next Priorities

1. Make chat a planner-driven action surface.
   - Use the LLM planner for open-ended chat intent instead of deterministic string matching.
   - Keep backend validation, allow-listed tools, and approval requirements outside the model.
   - Add a richer confirmation UI for mutating actions such as saving jobs, updating profile memory, generating resume versions, and saving prep plans.

2. Move LangGraph into one real workflow early.
   - Keep the native executor as a learning baseline and fallback.
   - Use the `WorkflowRuntime` boundary so prep planning runs on LangGraph when installed and native otherwise.
   - Make LangGraph the intended primary runtime for stateful orchestration once it cleanly supports pause/resume, approvals, retries, and traceable graph state.

3. Expand analysis-quality evaluation.
   - Add more real-world eval cases from saved job mistakes.
   - Track model, prompt version, schema version, and eval output snapshots.
   - Add eval cases for resume guidance and prep-plan quality.

4. Strengthen the workflow runtime.
   - Add cache keys for reusable intermediate outputs.
   - Add model routing and cost accounting.
   - Add retry and failure policies.
   - Persist workflow traces beyond the current `AgentTask` artifacts.
   - Add human approval pauses for high-cost, low-confidence, or externally visible actions.

5. Add structured memory before semantic memory.
   - Keep improving profile, saved-job, prep-plan, resume, coding-practice, and interview-story records.
   - Add embeddings and retrieval only after the structured memory contracts are stable.
   - Use RAG for retrieving relevant resume bullets, past job analyses, prep notes, and interview stories.

6. Improve public demo quality.
   - Keep UI polished enough for GitHub demos.
   - Keep backend architecture as the main portfolio story.

## Skill Focus For AI / Agentic SDE Roles

Employer signals point to six skill groups. CareerPilot should teach them in this order:

| Priority | Skill group | Why it matters | CareerPilot mapping |
| --- | --- | --- | --- |
| 1 | Agent workflow runtime | Agentic apps are increasingly about stateful, multi-step tool orchestration rather than one prompt. | DAG workflows, tool registry, planner/evaluator/aggregator nodes, approval gates, retries, traces. |
| 2 | Evaluation and observability | Production AI systems need trust, regression tests, provenance, and failure analysis. | Golden evals, fit validation, artifact provenance, prompt/model/schema versions, trace replay. |
| 3 | Memory and RAG | Useful agents need durable context, but retrieval should sit on top of clear data contracts. | Structured profile/job/prep/coding memory first; embeddings and semantic retrieval later. |
| 4 | Production backend and distributed systems | Senior AI platform roles still value core backend depth: workers, queues, consistency, scale, failure recovery. | Repository/service boundaries, durable workflow state, workers, background tasks, trace persistence. |
| 5 | Cloud-native infrastructure | Cloud, Docker, and Kubernetes matter when the app has clear runtime boundaries to deploy. | Containerized FastAPI, React, worker process, health checks, cloud deployment, later Kubernetes split. |
| 6 | Kafka/Flink and streaming systems | Valuable for AI/data platform roles, but only once CareerPilot has real workflow events to analyze. | Workflow event bus, skill-gap trend aggregation, prep progress analytics, coding-practice analytics. |

Research signals behind this prioritization:

- Distributed systems roles still emphasize production Java/Scala/C++, algorithms, databases, big-data systems, cloud storage, pipelines, query engines, and operating large-scale systems. See the [Databricks distributed systems role](https://www.databricks.com/company/careers/engineering---pipeline/senior-software-engineer---distributed-data-systems-6936994002).
- Large AI labs continue to hire for deep infrastructure and large-scale computing systems. See [Business Insider on OpenAI infrastructure hiring](https://www.businessinsider.com/openai-data-center-infrastructure-hiring-push-2025-4).
- Agentic software engineering research highlights orchestration, verification, and human-AI collaboration. See [Rethinking Software Engineering for Agentic AI Systems](https://arxiv.org/abs/2604.10599).
- Agentic workload research describes agents as stateful, multi-turn systems with repeated model calls, tool execution, and long-lived context. See [Agentic AI Workload Characteristics](https://arxiv.org/abs/2605.26297).
- Agent-skill research emphasizes reusable guidance, execution policy, termination criteria, evaluation, and security/governance. See [SoK: Agentic Skills](https://arxiv.org/abs/2602.20867).
- Kubernetes and cloud-native deployment are useful platform skills, but they should support the agentic-runtime story instead of becoming a separate side quest. See [Kubernetes overview](https://www.itpro.com/enterprise-applications/31654/what-is-kubernetes) and [KubeIntellect](https://arxiv.org/abs/2509.02449).

## Deferred Work

- Broad target-company scans and cron jobs.
- Cloud deployment.
- Postgres or vector-store migration.
- LangGraph becomes the primary runtime after one workflow proves clean pause/resume, approval, retry, and trace semantics behind CareerPilot-owned contracts.
- Docker/Kubernetes deployment after API, frontend, worker, and persistence boundaries are clean.
- Kafka/Flink after workflow events exist and analytics questions are real.
- Multi-user auth.

These are valuable, but they should follow stronger single-job quality, workflow observability, and evaluation.

## Decision Log

### SQL First

SQLite is the right local persistence layer for this stage because the app has relational state: jobs, statuses, analysis versions, chat sessions, prep plans, resume versions, and profile proposals. A future hosted version can move behind repository interfaces to Postgres.

### Required LLM Semantic Scoring

Career-transition fit is semantic. The app should not manufacture user-facing recommendations from keyword scoring when the LLM scorer is unavailable. Deterministic code is still useful for parsing normalization, evidence validation, schema migration, and stable eval checks.

### Chat Requires LLM Semantics

Free-form chat should not pretend to understand the user with deterministic canned responses. If LLM chat is unavailable, CareerPilot returns an explicit unavailable message. Deterministic code remains appropriate for explicit UI actions, typed API calls, schema validation, and safety checks.

### Canonical Labels For LLM Output

Natural-language LLM explanations are useful for users but brittle for product contracts. CareerPilot stores canonical concern, gap, and growth-area labels for tests, UI grouping, and historical analysis while preserving flexible prose for explanations.

### Review-First Saved Analysis Updates

Regeneration creates a candidate analysis. The user explicitly applies it to a saved job. This preserves application status, keeps historical versions, and avoids silent destructive updates.

### Target Companies Before Open-Web Discovery

The user’s job search is focused on large target companies. A curated watchlist is more useful and reliable than scraping the whole internet. Scheduled discovery should wait until manual ingestion is reliable.

### LangGraph As Runtime, Not Domain Model

CareerPilot should not over-invest in a custom workflow engine. The native DAG executor is useful as a learning baseline and fallback, but LangGraph is the intended primary runtime for stateful orchestration once the planner and workflow contracts are stable. CareerPilot still owns domain models, tool allow-lists, persistence, evals, prompts, cost policy, and API contracts.

### Cloud, Kubernetes, And Streaming Later

Cloud deployment, Kubernetes, Kafka, and Flink are valuable learning goals, but they should arrive when CareerPilot has production-shaped runtime problems. Deploying the app before workflow state, evaluation, trace persistence, and worker boundaries are clear would mostly teach hosting. Deploying after those boundaries are clear teaches AI-platform engineering.

## How To Use This Roadmap

- Use this file for project status and next-step planning.
- Use [Architecture](architecture.md) for what exists now.
- Use [Workflow Runtime](workflow_runtime.md) for the agentic-runtime transition.
- Use [Learning Guide](learning_guide.md) for concepts and interview learning.
