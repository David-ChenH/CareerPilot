# Project Roadmap

This document is the top-level plan for CareerPilot. Feature-specific docs explain individual areas in more detail, but this roadmap explains how the whole system should evolve.

## Project vision

Build a local-first AI career workbench that helps users:

- maintain a private profile of background, skills, and preferences
- analyze job descriptions against that profile
- track applications and source links
- understand role fit and career-transition value
- generate prep plans and resume guidance
- ask follow-up questions about a specific analysis
- use web search for interview prep, company context, and recent signals
- later monitor target companies and scheduled job discovery

The project is also a learning vehicle for production-style agentic applications.

## Product principles

1. Local-first by default
   - Private profile and application data stay on the user's machine.
   - Cloud deployment is optional later, not required for the MVP.

2. Depth before breadth
   - Make single-job analysis, prep planning, and follow-up chat excellent before broad discovery.
   - Discovery multiplies whatever quality level the analysis workflow has.

3. LLM-led judgment with narrow deterministic support
   - Use LLM semantic scoring as the required intelligence layer for job-fit recommendations.
   - Keep deterministic code for parsing normalization, evidence validation, and stable regression tests.

4. Human-in-the-loop for sensitive state
   - Profile updates, resume facts, and application status changes should be explicit and auditable.
   - Chat should propose memory updates rather than silently rewriting the profile.

5. Layered ingestion and research
   - Manual paste and URL fetch first.
   - Browser rendering for JavaScript-heavy pages.
   - OpenAI web search for research and discovery when useful.
   - ATS connectors and scheduled scans later.

6. Explainable recommendations
   - Scores should include matches, gaps, concerns, reasoning, and transition notes.
   - Explanations are both user experience and debugging tools.

7. Portfolio-grade engineering
   - Keep architecture docs, tests, and tradeoff notes updated.
   - The project should be explainable in interviews.
   - Frontend polish should support the backend/agent story rather than becoming the main engineering focus.

## Current state

Implemented:

- FastAPI backend.
- Static frontend UI.
- React sidebar workspace with Dashboard, Analyze Job, Applications, Assistant, Profile, and Settings areas.
- Private profile template and local ignored profile pattern.
- Pasted job description analysis.
- Simple URL fetch for readable HTML job pages.
- Playwright browser fallback for URL fetching.
- SQLite application tracker.
- Source URL storage.
- Internal-transfer versus external-application classification for saved jobs.
- Background link analysis/save workflow with persistent `AgentTask` lifecycle and task polling.
- Global Assistant can detect a pasted job URL and invoke the allow-listed `ingest_job_from_url` action, reusing the persistent background workflow.
- Context-budget compaction for oversized fetched job pages, with original and compacted lengths recorded in `AgentTask` artifacts.
- Chunked LLM extraction for oversized pages: selected chunks are parsed into structured facts and merged before final scoring/guidance.
- Evidence-grounded fit analysis: LLM matches, gaps, concerns, recommendations, and guidance can carry job evidence, profile signals, severity, and confidence.
- Requirement-strength-aware fit analysis: keep hard gaps separate from optional or ambiguous growth areas, treat accepted language lists as alternatives, and preserve uncertain qualification tiers when source headings are lost.
- Self-evolving career-page selector observations: learn safe declarative content-root selectors by careers domain, promote them after repeated successful validation, and rediscover them when page structure drifts.
- Preview-first job analysis with explicit `Save to tracker`.
- Full analysis payload persistence for explicitly saved jobs, including refresh when an existing saved job is re-analyzed.
- Versioned current analysis projections with append-only snapshots and explicit payload migrations.
- Shared artifact provenance for job analysis, prep plans, targeted resume PDFs, and profile proposals.
- Append-only prep-plan revisions, persisted resume versions, profile-proposal revisions, and accepted-profile snapshots.
- Application status updates.
- Job deletion.
- Saved job detail drawer with job-scoped chat.
- Split saved-application drawer with analysis on the left and streaming job chat on the right.
- Personal Profile page that displays local profile memory.
- Resume portal that extracts proposed profile updates from pasted Markdown/plain-text resume content.
- Confirm-and-save profile memory updates with local audit logging.
- Deterministic parsing normalization and parser fallback.
- Optional LLM-backed structured parsing.
- Required LLM-backed semantic scoring for job-fit recommendations.
- Optional LLM-backed application guidance.
- Initial saved-job follow-up chat with local message persistence.
- Global assistant chat with local persistence for cross-job planning questions.
- Optional OpenAI web search in saved-job chat with persisted citations.
- Local `.env` loading for private API keys.
- Tests for analysis, deduplication, source URLs, deletion, parser fallback, and scorer behavior.
- Initial job-analysis eval harness with frozen profile, representative fixtures, CLI, JSON report mode, and regression tests.
- Learning, architecture, and tradeoff docs.

Known limitations:

- URL fetch can still fail for blocked, login-required, or heavily dynamic pages.
- LLM extraction and semantic scoring need broader evaluation cases beyond the initial harness.
- UI shell is more scalable, but Settings is still a placeholder.
- Prep planning is not yet a first-class workflow.
- Resume tailoring is not yet a first-class workflow.
- Web-search chat needs more evaluation and prompt specialization for interview/company research.
- No OpenAI web search integration yet.
- Target-company scan and scheduled discovery are intentionally delayed.

## Phase 0: Foundation

Status: mostly complete.

Goal:

Create a local app that can analyze pasted jobs and track applications.

Milestones:

- Project scaffold.
- FastAPI routes.
- Static UI.
- YAML profile memory.
- SQLite tracker.
- Job analysis workflow.
- Delete/status/source URL support.
- Basic tests.

Exit criteria:

- User can paste or fetch a job, analyze it, save it, update status, and delete it.
- App does not require cloud deployment.
- Private data is ignored by Git.

## Phase 1: Reliable single-job analysis

Status: in progress.

Goal:

Make analysis of one job accurate, semantic, and useful for career-transition decisions.

Milestones:

1. LLM-backed structured extraction
   - Status: initial implementation complete.
   - Extract title, company, location, seniority, skills, requirements, responsibilities, compensation, and role focus.
   - Use strict Pydantic schemas.
   - Keep deterministic parser as fallback.

2. LLM semantic scoring
   - Status: initial implementation complete.
   - Score role alignment, skill match, career-transition value, seniority fit, and learning ROI.
   - Use the LLM score as the required job-fit recommendation.
   - Return an explicit unavailable response when semantic scoring cannot run.

3. Analysis quality evaluation
   - Status: initial implementation complete.
   - Representative job fixtures live under `evals/job_analysis/cases.yaml`.
   - A frozen eval profile lives under `evals/profiles/backend_ai_platform.yaml`.
   - The `careerpilot-eval` CLI reports pass/fail results for the LLM-backed analysis workflow.
   - Next: expand cases with real target-company roles, add graded quality checks, and compare LLM reports across prompt changes.

4. Better analysis output
   - Status: initial review workspace complete.
   - Show "why apply", risks, gaps, prep actions, resume positioning, interview focus, and parsed role signals.
   - Separate role-fit reasoning from prep planning.
   - Surface risks and missing context clearly.
   - Capture local analysis feedback for later eval and prompt-improvement loops.

5. Preview-first save workflow
   - Status: initial implementation complete.
   - Analyze/fetch produces a preview without mutating the tracker.
   - `Save to tracker` writes the reviewed analysis into SQLite.
   - Keep analysis results scrollable so long LLM output does not push the workflow controls away.

6. Preview analysis chat
   - Status: initial implementation complete.
   - Let users ask clarification questions about an unsaved analysis before committing it to the tracker.
   - Support optional web search for current company/team context during analysis review.
   - Keep preview chat ephemeral until the job is saved.

7. Unified assistant context
   - Status: initial backend endpoint and shared frontend panel started.
   - Add `POST /assistant/chat` with contextual focus.
   - Supported focus types begin with `global`, `analysis_preview`, and `saved_job`.
   - Treat focus as a priority signal, not a hard wall; shared memory can still inform answers.
   - Keep durable writes separate from chat.

8. Agent task lifecycle
   - Status: initial manual implementation complete for background job-link ingestion.
   - Persist task input, status, step history, artifacts, and errors in SQLite.
   - Current task steps: `fetch_job`, `analyze_job`, `save_job`.
   - Next: generalize this for prep plans, resume drafts, profile updates, and research tasks; then evaluate whether LangGraph should own task execution.

9. Self-evolving selector observations
   - Status: initial local learning loop and gated semantic validation complete.
   - Learn declarative content selectors per careers domain without generating executable scraper code.
   - Promote a selector after repeated validated extractions.
   - Return a selector to candidate state and rediscover content roots when extraction quality drops.
   - Next: persist observation history, expose selector inspection in Settings, and cache LLM analysis by posting-content hash plus workflow/profile version.

Exit criteria:

- User trusts the analysis enough to decide whether a role is worth applying to.
- Tests/evals catch obvious regressions in parsing, scoring, and recommendation quality.

## Phase 2: Prep plan and resume guidance

Status: next priority.

Goal:

Turn a job analysis into concrete preparation and application guidance.

Milestones:

1. Prep planner
   - Status: initial guidance generator complete, needs dedicated workflow and UI.
   - Generate a plan based on gaps, role type, interview timeline, and company context.
   - Include system design, coding, behavioral, and role-specific topics.
   - Distinguish immediate prep from longer-term skill building.

2. Resume tailoring
   - Status: initial resume guidance list complete, needs richer workflow.
   - Suggest truthful resume emphasis.
   - Connect existing experience to job requirements.
   - Avoid invented experience.

3. Skill gap learning plan
   - Explain gaps as `critical`, `useful`, or `nice-to-have`.
   - Recommend targeted learning resources or mini-projects.

4. Saved-job actions
   - Generate prep plan for a saved job.
   - Generate resume guidance for a saved job.

Exit criteria:

- User can move from "this role looks interesting" to a concrete application/prep plan.
- The app clearly distinguishes real experience from suggested learning.

## Phase 3: UI experience

Status: next priority.

Goal:

Make the app feel like a usable job-search workbench rather than a raw API demo, while keeping the main learning focus on backend and agent architecture.

Milestones:

1. Analysis result redesign
   - Show recommendation, semantic score, transition value, gaps, risks, and prep actions.
   - Show one semantic score with inspectable evidence.

2. Application tracker redesign
   - Status: initial implementation complete; tracker summaries now include team/business context.
   - Make saved jobs easier to scan.
   - Distinguish similar roles by showing what the hiring team/product/business area does.
   - Add selected-job detail drawer.
   - Keep status updates and delete actions ergonomic.

3. Better loading and error states
   - Clearly distinguish fetch failure, browser failure, LLM setup failure, and model/API failure.
   - Offer a manual-paste fallback where useful.

4. Responsive polish
   - Keep the local app usable on laptop and narrow browser widths.
   - Avoid clutter as more analysis fields appear.

5. Frontend scope control
   - Decision: migrate to a React/TypeScript workbench before adding job-scoped chat.
   - Rationale: selected-job detail, persisted analysis, upcoming chat, web-search toggles, and richer loading/error states are now stateful enough that the static UI will slow iteration.
   - Keep frontend scope controlled: the React app should demonstrate the agent workflow clearly without becoming the main engineering focus.

Exit criteria:

- User can analyze, inspect, save, and revisit jobs without relying on API docs.
- The UI supports deeper analysis without becoming visually overwhelming.
- The UI looks credible for a portfolio demo without distracting from the backend system design story.

## Phase 3A: React workbench migration

Status: next priority.

Goal:

Replace the static HTML/JavaScript UI with a small, production-shaped React workbench that can support richer saved-job analysis, follow-up chat, and web-search controls without rewriting the backend.

Recommended stack:

- React + Vite + TypeScript for a modern but lightweight frontend.
- TanStack Query for API fetching, caching, loading states, and invalidation.
- Tailwind CSS for fast, consistent demo-quality styling.
- Keep FastAPI as the backend API and serve the built frontend later if useful.
- Node 24 LTS as the frontend runtime baseline. The repo declares this through `.nvmrc`, `.node-version`, and the frontend package `engines` field.

Initial milestones:

1. Create a `frontend/` app.
   - Status: initial scaffold complete.
2. Add typed API client models matching FastAPI responses.
   - Status: initial implementation complete.
3. Rebuild the current workflow:
   - paste or fetch a job
   - analyze and save
   - list saved jobs
   - select a job
   - show persisted analysis detail
   - update status
   - delete jobs
   - Status: initial implementation complete.

6. Sidebar workspace shell
   - Status: initial implementation complete.
   - Add Dashboard, Analyze Job, Applications, Assistant, Profile, and Settings navigation.
   - Keep Settings as an explicit placeholder until backend workflow controls are added.

7. Saved job detail drawer
   - Status: initial implementation complete.
   - Move saved analysis and job-scoped chat out of the always-visible page layout.
   - Use a split drawer so job-specific chat stays visible beside the analysis.
4. Keep the existing static UI until the React UI reaches feature parity.
5. After parity, make React the default local UI and keep FastAPI docs available for API exploration.

Interview learning value:

- Shows separation between backend agent workflow and frontend client.
- Demonstrates typed API contracts and state management.
- Creates a better surface for job-scoped chat and web-search research without changing the core backend design.

## Phase 4: Interactive analysis chat with web search

Status: in progress.

Goal:

Let users ask follow-up questions about a saved job analysis, optionally using web search for recent company or interview context.

Milestones:

1. Analysis chat endpoint
   - Status: initial implementation complete.
   - Add `POST /jobs/{job_id}/chat`.
   - Add `POST /jobs/{job_id}/chat/stream` for progress and answer streaming.
   - Include profile, persisted analysis payload, source URL, and application status as context.

2. Chat persistence
   - Status: initial implementation complete.
   - Store chat messages locally.
   - Keep conversation scoped to a job unless user explicitly asks to update profile memory.

3. Global assistant
   - Status: session-based implementation complete.
   - Add `GET /chat` and `POST /chat`.
   - Add `GET /chat/sessions`, `POST /chat/sessions`, and `DELETE /chat/sessions/{session_id}`.
   - Use profile, saved job summaries, application statuses, and global chat history.
   - Scope history by chat session so users can start fresh conversations without losing older planning threads.
   - Keep this separate from job-scoped chat so broad planning does not require selecting a job.

3a. Unified assistant façade
   - Status: initial implementation complete.
   - Add `POST /assistant/chat` as the forward-compatible assistant interface.
   - Route contextual focuses to the existing global, saved-job, or analysis-preview chat behavior.
   - Migrate UI surfaces gradually instead of rewriting all chat paths at once.

4. Web search mode
   - Status: initial implementation complete.
   - Add optional OpenAI web search for current company news, recent interview reports, and public role context.
   - Keep ordinary job-analysis chat usable without web search.
   - Cite sources when web search is used.

5. Tool boundaries
   - Do not let chat silently modify profile memory.
   - Profile updates should be proposed and confirmed.

6. Chat history UX
   - Status: session-based implementation complete.
   - Provide a ChatGPT-style session list for the global Assistant.
   - Let users start a fresh chat, select older chats, clear a thread, or delete a session.
   - Migrate older flat global history into a "Previous conversation" session.

## Phase 5: Profile and resume memory

Status: in progress.

Goal:

Make user background and preferences visible, auditable, and updateable through resume/profile workflows.

Milestones:

1. Profile page
   - Status: initial implementation complete.
   - Display the currently loaded local/example profile.
   - Clearly show whether the app is using private local memory or the example template.

2. Resume portal
   - Status: proposal, refinement, and save workflow implemented for Markdown/plain-text content.
   - Upload or paste resume text.
   - Extract proposed technical strengths, experience highlights, and preference signals.
   - Do not silently write to `profile.local.yaml`; require explicit user confirmation.
   - Let the user chat with a proposal assistant before saving.

3. Confirm-and-save profile updates
   - Status: initial implementation complete.
   - Let the user approve proposed updates before modifying local profile memory.
   - Keep an audit trail of accepted profile changes.
   - Store accepted update records in `data/profile_audit.jsonl`.

4. Generic proposal pattern
   - Status: initial pattern established.
   - Tools should return proposed structured changes rather than mutating memory directly.
   - Chat can refine a proposal, but only a confirm endpoint writes durable state.
   - Future tools can reuse this pattern for target-company preferences, resume tailoring, prep plans, and application notes.

5. Prep plan workspace
   - Status: initial implementation complete.
   - Generate a daily prep checklist from timeline, hours per day, focus areas, and optional saved job context.
   - Import pasted prep plans into checklists.
   - Persist checklist completion locally in SQLite.

6. Resume generation workspace
   - Status: initial implementation complete.
   - Generate role-targeted PDF drafts from local profile memory and optional saved job context.
   - Keep the output as a reviewable draft rather than an automatic application artifact.

Exit criteria:

- User can ask "why is this a good fit?", "what should I study first?", "how should I tailor my resume?", and "what recent company context matters?" from the job page.
- Web-search answers cite sources when search is used.

## Phase 6: Agent orchestration

Status: planned.

Goal:

Introduce agent workflows where they improve analysis, prep, or chat quality.

Candidate workflows:

- chat-invoked job ingestion
- prep planner agent
- resume tailoring agent
- company research agent
- profile update proposal agent
- interview plan agent

Possible tools:

- OpenAI Responses API tools
- OpenAI Agents SDK
- LangGraph
- direct tool calling with Pydantic schemas

Guideline:

Do not replace stable workflows with an agent just for novelty. Use agents where the system needs to inspect state, choose a strategy, call tools, and adapt.

Exit criteria:

- At least one workflow demonstrates meaningful tool use, state, human approval, and evaluation.
- Status: first action-registry workflow is implemented for chat-invoked job URL ingestion; next work should broaden the registry carefully instead of letting chat mutate arbitrary state.

## Phase 7: Target-company discovery and ingestion

Status: intentionally delayed.

Goal:

Monitor a curated list of target companies after the analysis/chat experience is strong.

Milestones:

1. Target company config
   - `target_companies.example.yaml`
   - ignored `target_companies.local.yaml`

2. Ingestion source abstraction
   - Common `JobSource` interface.
   - Source connectors return normalized raw postings.

3. Manual scan endpoint
   - `POST /companies/scan`
   - no cron until scan quality is reliable

4. Stronger ingestion connectors
   - Generic HTTP connector.
   - Browser connector.
   - Greenhouse/Lever/ATS connectors based on target-company needs.

5. Optional scheduled scans
   - Persist scan runs.
   - Produce daily summaries.
   - Add scheduling only after manual scans work.

Exit criteria:

- User can define target companies, run a manual scan, review relevant jobs, and later schedule scans.

Detailed doc:

- [Target Company Ingestion Plan](target_company_ingestion_plan.md)

## Phase 7: Production hardening

Status: planned.

Goal:

Make the project more credible as production-style engineering.

Milestones:

- Structured logging.
- Tracing for agent/tool calls.
- Error taxonomy.
- Better database migrations.
- Docker support.
- Optional Postgres/pgvector setup.
- Evaluation dashboard or reports.
- Security review for URL fetching, browser automation, and web search.

Exit criteria:

- Project can be discussed as a realistic AI/backend platform system, not just a demo.

## Phase 8: Cost-Aware Workflow Runtime

Status: planned next.

Goal:

Extract a reusable agent-workflow runtime inside CareerPilot so job analysis, prep planning, resume tailoring, and research can use dependency-aware execution, cache reuse, model routing, budget guardrails, retries, evaluation, approvals, and persistent traces.

Milestones:

1. Agent skills and reviewed extraction overrides
   - Status: framework-neutral agent-skill catalog, typed reviewed extraction overrides, Microsoft example, shared content-root strategies, and structural validation evidence complete.
   - Keep reusable `SKILL.md` guidance separate from optional reviewed site-specific overrides and local learned selector observations.
   - Keep executable behavior declarative and validated.

2. DAG runtime contracts
   - Status: typed models, dependency validation, cycle rejection, topological ready groups, minimal execution, allow-listed tools, dependency-output passing, failure blocking, in-memory traces, and background job-ingestion migration complete.
   - Define workflow, task, and run models.
   - Validate missing dependencies and cycles.
   - Compute dependency-ready task groups.

3. Parallel execution, cache, and cost
   - Run independent tasks concurrently when safe.
   - Cache reusable outputs by normalized inputs and versions.
   - Route model tiers transparently and enforce budgets.

4. Failure handling, evaluation, and approval
   - Add typed failures, retries, escalation, task evaluators, and approval pauses.
   - Persist trace events and task-run details.

5. Product migration
   - Status: background job ingestion runs through the runtime without changing the API contract.
   - Add an interview-prep DAG with parallel planning branches.

6. LangGraph comparison
   - Add a LangGraph adapter for one workflow after framework-neutral contracts are stable.
   - Document tradeoffs for persistence, interrupts, retries, observability, and operating complexity.

Detailed doc:

- [Agent Workflow Runtime Plan](workflow_runtime_plan.md)

## Decision log

### SQL first

Decision:

Use SQLite locally, with a future path to Postgres.

Reason:

The app has relational data: jobs, applications, statuses, companies, scan runs, resume versions, and prep plans. SQL is better for flexible queries and local development.

### Plain HTTP fetch first

Decision:

Start with simple server-side URL fetch before browser automation, then add Playwright as a fallback after observing JavaScript-rendered career pages.

Reason:

Plain HTTP is fast, simple, testable, and enough for static pages. Real-world failures such as JavaScript-rendered career portals justify the extra complexity of a browser fallback.

### Required LLM semantic score

Decision:

Use LLM semantic scoring as the only recommendation. Deterministic scoring was removed because low-quality fallback recommendations are worse than an explicit unavailable state.

Reason:

Career-transition fit is semantic. A role can be valuable even when it does not perfectly match current skills. LLM scoring can evaluate role alignment, transition value, learning ROI, and seniority realism more flexibly than keyword rules. If semantic scoring is unavailable, the app returns an explicit unavailable response rather than manufacturing a lower-quality recommendation.

### LLM-led skill and gap discovery

Decision:

Use LLM extraction/scoring as the primary mechanism for open-ended skills and gaps. Deterministic scoring should not produce user-facing skill gaps from keyword aliases; when semantic scoring is unavailable, the app should expose uncertainty instead of pretending a keyword table understands the role.

Reason:

Technology names and job requirements change constantly. Hardcoding every tool or framework does not scale and can produce brittle behavior. The model is better suited to infer skills such as streaming systems, managed Kubernetes, or agent infrastructure from natural language.

### Analysis and chat before scan automation

Decision:

Delay target-company scanning until the analysis result, prep planning, UI, and follow-up chat are strong.

Reason:

Discovery multiplies whatever quality level the analysis workflow has. It is better to make one-job understanding excellent before automating more job intake.

### Frontend as demo workbench

Decision:

Keep frontend work focused on presenting the backend/agent system clearly rather than turning the project into a frontend specialization exercise.

Reason:

The portfolio target is backend, AI platform, and production agentic systems engineering. A polished UI helps demonstrate the system, but the core interview value should come from orchestration, memory, tool use, evaluation, persistence, and architecture.

### Target companies before open-web search

Decision:

When discovery is implemented, prioritize a curated company watchlist over broad internet search.

Reason:

The user wants high-signal jobs from specific companies. This reduces noise and makes scheduled discovery more reliable.

### Manual scan before cron

Decision:

Build "Scan now" before scheduled scans.

Reason:

Scheduling unreliable ingestion only creates recurring noise. Manual scan should work first; cron is an automation wrapper around a stable workflow.

### Version durable generated artifacts

Decision:

Treat persisted LLM output as schema-versioned product data. Keep a normalized current projection for reads and append-only snapshots for historical analysis.

Reason:

Prompt improvements, model upgrades, and UI cleanup can reshape generated data after users have saved jobs. Explicit payload migrations let the current product evolve without silently destroying historical output. Apply this pattern before adding durable resume versions, prep-plan revisions, and profile-proposal history.

## How to use this roadmap

When adding a new feature:

1. Update the relevant phase.
2. Add or update a detailed design doc if the feature has important tradeoffs.
3. Add tests or eval cases.
4. Update README if the user workflow changes.
5. Add an interview framing note when the decision is useful to explain.

This keeps the project useful as both software and a learning artifact.
