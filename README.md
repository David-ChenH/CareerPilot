# CareerPilot

Local-first AI career workbench for analyzing jobs against a user's background, tracking applications, targeting resumes, and generating preparation suggestions.

CareerPilot is designed for people who want a private, customizable job-search workflow. Your personal background is stored in a local file that is ignored by Git.

## What it does

Given a saved user profile and a pasted job description, the app can:

- extract job details and detected skills
- fetch readable job text from a job link
- score how well the job matches the profile
- evaluate semantic fit for career-transition goals when LLM scoring is enabled
- generate prep, resume, learning, and interview-focus guidance when LLM guidance is enabled
- ask follow-up questions about a saved job using the local profile, saved analysis, and chat history
- ask the global assistant to compare saved jobs, plan prep, and reason across the local application tracker
- optionally use OpenAI web search in job chat for current company/interview/product research
- view a personal profile page showing local profile memory
- upload or paste resume text to extract proposed profile updates
- explain strengths, gaps, and concerns
- suggest resume emphasis points
- suggest interview prep topics
- save the job to a local SQLite tracker
- infer whether a saved job is an internal transfer or external application from the local profile and job company
- save a job link in the background, analyze it, and automatically add it to the tracker when complete
- regenerate a saved job's analysis from its detail drawer
- refresh a saved job in place when you analyze the same source link again
- preserve versioned snapshots when saved analysis is re-analyzed or migrated
- preserve prep-plan revisions, targeted resume PDF versions, profile-proposal history, and accepted-profile snapshots locally
- update application status
- open or delete saved jobs from the tracker

The model is the source of user-facing semantic skills, gaps, and fit recommendations. If semantic scoring is unavailable, CareerPilot returns an explicit unavailable response instead of presenting a keyword-based fallback score as meaningful analysis.

New analyses can include evidence for important claims. Matches, gaps, risks, recommendations, and guidance may carry job evidence, profile signals, severity, and confidence so users can inspect why the assistant believes something.

Current focus: pasted job descriptions, individual job links, application tracking, and assistant workflows. Automated job discovery is planned later.

## Quick start

### 0. Use Node 24 LTS for the React frontend

The backend is Python-first, but the demo workbench uses React. The repo includes:

```text
.nvmrc
.node-version
```

Both point to Node 24, the recommended LTS line for this project.
The frontend also uses `engine-strict=true`, so `npm install` should fail clearly if you are on an older Node version.

If you use `nvm`:

```bash
nvm install
nvm use
```

If you do not use a Node version manager yet, install Node 24 LTS from the official Node.js site or with your preferred version manager before running the frontend.

### 1. Create a Python environment

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```bash
pip install -e ".[dev]"
```

This installs the app in editable mode plus development tools such as `pytest`.

To enable browser-rendered job fetching for JavaScript-heavy career pages, install the browser extra:

```bash
pip install -e ".[dev,browser]"
playwright install chromium
```

To enable LLM-backed structured job parsing, install the AI extra and set an API key:

```bash
pip install -e ".[dev,ai]"
export OPENAI_API_KEY="your_api_key_here"
```

You can combine extras:

```bash
pip install -e ".[dev,browser,ai]"
```

You can also store the key in a local `.env` file:

```bash
cp .env.example .env
```

Then edit `.env`:

```text
OPENAI_API_KEY=your_api_key_here
JOB_AGENT_LLM_MODEL=gpt-4o-mini
JOB_AGENT_WEB_SEARCH_MODEL=gpt-5.4-mini
```

`.env` is ignored by Git. Restart the server after changing it.

### 3. Create your private profile

```bash
cp app/memory/profile.example.yaml app/memory/profile.local.yaml
```

Edit:

```text
app/memory/profile.local.yaml
```

Add your background, target roles, skills, preferences, and avoid-list.

`profile.local.yaml` is ignored by Git. Do not commit private resume details, job preferences, or application history.

If no local profile exists, the app uses the generic example profile.

You can also use the Profile page to paste or upload resume text, review proposed profile updates, refine the proposal with the assistant, and explicitly save accepted facts into `profile.local.yaml`. Accepted changes are logged locally under `data/profile_audit.jsonl`, which is also ignored by Git.

The global Assistant can also apply direct corrections when you explicitly ask it to update profile memory, for example: "update my education background: ...". These changes still write only to the local ignored profile file and audit log. Ambiguous resume/profile extraction should continue through the Profile page proposal review flow.

### 4. Run the app

```bash
uvicorn app.main:app --reload
```

Open the UI:

```text
http://127.0.0.1:8000
```

Open the API docs:

```text
http://127.0.0.1:8000/docs
```

## Using the UI

### Current FastAPI-served UI

1. Use `Job Link` mode when you have a job URL. Click `Fetch & Analyze` to fetch and analyze the job as a preview.
   Use `Save in background` when you already know the link is worth tracking and want CareerPilot to fetch, analyze, and save it without blocking the review workspace.
2. Use `Paste Text` mode when URL fetching fails or when you already copied the job description.
3. Review the score, matches, gaps, resume emphasis, and prep topics in the scrollable analysis panel.
4. Use `Ask About This Analysis` to question concerns, request clarification, or enable web search for current company/team context before saving.
5. Click `Save to tracker` only after you decide the job is worth tracking.
6. Use the tracker panel to open the original link, update status, or delete a saved job.

The React workbench hides fetched job text by default in `Job Link` mode. Use `View fetched text` only when you want to inspect or debug what the fetcher extracted.

The older FastAPI-served static UI follows the original workflow:

1. Paste a job description into the text area, or paste a job link and click "Fetch link".
2. Keep "Save job to tracker" checked if you want to store it.
3. Click "Analyze" for pasted text.
4. Review the score, matches, gaps, resume emphasis, and prep topics.
5. Use the tracker panel to open the original link, update status, or delete a saved job.

The React workbench follows a preview-first pattern: analysis tools produce output first, and durable state changes happen through explicit save/apply buttons.

Assistant chat is moving toward a unified context model. The backend exposes `POST /assistant/chat`, where each request includes an active focus such as `global`, `analysis_preview`, or `saved_job`. The active focus guides the answer, while shared memory such as profile and saved jobs can still be used when relevant.

Saved jobs are stored locally in:

```text
data/jobs.sqlite3
```

The `data/` directory is ignored by Git.

### CareerPilot React UI

The React frontend is the recommended direction for richer demo and chat workflows.

Run the backend in one terminal:

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

Run the frontend in another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

The Vite dev server proxies API calls to the FastAPI backend on `http://127.0.0.1:8000`.

The CareerPilot workbench is organized as a sidebar workspace:

- `Dashboard`: workflow summary and next actions.
- `Analyze Job`: link/paste analysis flow.
- `Applications`: saved jobs and status tracking.
- `Prep Plan`: generated or imported daily preparation checklists.
- `Resume`: role-targeted PDF resume draft generation.
- `Assistant`: global assistant for cross-job and career-planning questions.
- `Profile`: local profile memory plus resume upload/profile extraction.
- `Settings`: planned local profile and model/API configuration.

The `Analyze Job` page is now an analysis review workspace. It separates decision summary, apply reasoning, risks, skill gaps, prep actions, resume positioning, interview focus, and parsed role signals. Each section can seed an assistant question, and the page can directly hand off to prep-plan generation or resume drafting. Saving a job remains an explicit action after review.

Saved job cards show team/business context, role summary, highlighted tech stack, status, source link, and delete actions.
They also show whether the role appears to be an `Internal transfer` or `External` application based on the current company in the local profile and the parsed job company.
Saved job details open in a drawer from `Applications`, keeping the tracker easier to scan while preserving deeper analysis and job-scoped chat.
The drawer uses a split layout: analysis and guidance on the left, job-specific chat on the right. Job chat streams progress states and answer text so the user is not left waiting on a blank UI. Chat history is hidden by default so each session starts clean; use `Load history` when you want to revisit older messages.

The `Prep Plan` page can generate a checklist from a target timeline, hours per day, optional saved job, and focus areas such as Kubernetes or LeetCode. You can also paste an existing plan and import it as daily checklist items.

The `Resume` page generates a PDF draft from local profile memory, optional saved job context, and role-specific notes. The PDF is a starting draft and should be reviewed before submitting.

Analysis feedback is stored locally in `data/analysis_feedback.jsonl`. Marking an analysis as accurate, missing a gap, wrong about a concern, or too generic creates review data that can later become eval cases or prompt-improvement examples.

## Using the API

Analyze a job:

```http
POST /jobs/analyze
```

Example body:

```json
{
  "description": "Senior Backend Engineer, AI Platform\nCompany: Example AI\nLocation: Remote\n\nBuild backend APIs and workflow orchestration for LLM agent systems.",
  "save": true
}
```

Fetch a job page, extract readable text, analyze it, and save the source URL:

```http
POST /jobs/fetch-and-analyze
```

Example body:

```json
{
  "url": "https://company.example/jobs/senior-backend-engineer",
  "save": true
}
```

Some job boards render descriptions with JavaScript or block automated requests. In those cases, paste the job description manually.

Start a background link save:

```http
POST /jobs/background-fetch-and-save
```

Regenerate a saved job's analysis from its stored source link:

```http
POST /jobs/{job_id}/regenerate-analysis
```

Regeneration runs as a background task. Saving the same source link updates the existing tracker row, preserves application status, and appends an analysis-version snapshot instead of creating a duplicate application.

Example body:

```json
{
  "url": "https://company.example/jobs/senior-backend-engineer",
  "save": true,
  "use_browser_fallback": true,
  "use_llm": true,
  "use_llm_guidance": true
}
```

Poll task status:

```http
GET /jobs/background-tasks/{task_id}
```

Completed tasks include the saved job record.
Background link saves are represented as persistent `AgentTask` records with step history:

```text
queued
  -> fetch_job
  -> analyze_job
  -> save_job
  -> completed | failed
```

This is the first explicit agent task lifecycle in the project. It makes tool execution inspectable now and gives us a clean migration path toward a graph/worker orchestration framework later.

Very large fetched pages are handled with context budgeting before analysis. Some career portals return search-result chrome, embedded state, or many repeated listings with the job detail, which can exceed the model context window. When LLM parsing is enabled, CareerPilot selects high-signal chunks, extracts structured job facts per chunk, merges those facts, and then runs final scoring/guidance on the merged job. It still records both `original_description_length` and `description_length` on the task artifact when compaction happens.

For individual URL analysis, CareerPilot combines schema.org `JobPosting` JSON-LD metadata with Playwright-rendered content by default. JSON-LD provides clean canonical metadata; rendered extraction preserves visible heading and list structure. The resulting typed section artifact is sent to the LLM for semantic classification rather than relying on a fixed catalog of heading names. If Playwright is unavailable, CareerPilot retains the HTTP extraction as a resilient fallback.

Playwright extraction also records local learned selector observations per careers domain. After repeated successful structural validations plus gated semantic validation when required, later visits try the promoted CSS content-root selector first so the LLM receives a smaller, cleaner posting instead of the full rendered page. Optional reviewed overrides handle selected exceptional sites before bounded discovery runs. Learned observations live under the ignored `data/` directory and never contain generated executable code.

Security note: the URL fetch endpoint is intended for local personal use. If you deploy this app publicly, add URL allowlists or network egress controls before exposing it.

Troubleshooting job links:

- If clicking "Fetch link" appears to do nothing, hard refresh the browser tab so it loads the latest JavaScript.
- If the app says Playwright or Chromium is missing, run `pip install -e ".[dev,browser]"` and `playwright install chromium`.
- If the app reports that both plain fetch and browser fetch failed, open the job link in your browser, copy the job description, paste it into the text area, and click "Analyze".
- If a fetched career page is very large, CareerPilot uses chunked extraction plus compaction before LLM scoring. This prevents context-window failures, but pasted job text can still produce a cleaner analysis when the source page is mostly search results or repeated navigation text.
- Some sites may still block browser automation or require login.

List saved jobs:

```http
GET /jobs
```

Update application status:

```http
PATCH /jobs/{job_id}/status?status=applied
```

Delete a saved job:

```http
DELETE /jobs/{job_id}
```

List local chat history for a saved job:

```http
GET /jobs/{job_id}/chat
```

Ask a follow-up question about a saved job:

```http
POST /jobs/{job_id}/chat
```

Stream a follow-up answer with progress events:

```http
POST /jobs/{job_id}/chat/stream
```

The stream uses newline-delimited JSON events:

```json
{"type": "status", "message": "Loading saved job context"}
{"type": "chunk", "text": "Start with Kubernetes..."}
{"type": "done", "message": {"role": "assistant"}}
```

Example body:

```json
{
  "message": "How should I prepare for this role in two weeks?",
  "use_llm": true
}
```

The chat uses the saved job, persisted analysis payload, local profile, and prior chat messages. Chat history is stored locally in the same SQLite database as the application tracker.

Set `use_web_search` to `true` only for questions that need current external context, such as recent company news, product launches, or public interview-prep signals. Web-search answers store source citations locally and the React UI displays those links under the assistant message.

List assistant chat sessions:

```http
GET /chat/sessions
```

Create a fresh assistant chat:

```http
POST /chat/sessions
```

List messages for one assistant chat:

```http
GET /chat?session_id=1
```

Ask the global assistant:

```http
POST /chat
```

Example body:

```json
{
  "message": "Rank my saved jobs for AI platform transition.",
  "session_id": 1,
  "use_llm": true,
  "use_web_search": false
}
```

The global assistant uses the local profile, saved job summaries, application statuses, and the selected chat session history. It is separate from job-scoped chat so broad planning questions do not require selecting a specific job. If `session_id` is omitted, CareerPilot creates a new chat session from the first message. Existing pre-session history is migrated into a local "Previous conversation" session.

If the message includes a job URL and asks to analyze, save, track, or ingest it, the assistant routes the request through the `ingest_job_from_url` action. That action creates the same persistent `AgentTask` used by the background save button, then the UI polls the task and shows fetch/analyze/save progress inside the chat. This keeps chat flexible while the actual workflow remains deterministic and observable.

Clear one assistant chat:

```http
DELETE /chat?session_id=1
```

Delete one assistant chat:

```http
DELETE /chat/sessions/1
```

Unified assistant endpoint:

```http
POST /assistant/chat
```

Example body:

```json
{
  "message": "Explain whether this concern is supported by the job description.",
  "focus": {
    "type": "analysis_preview",
    "analysis": {}
  },
  "history": [],
  "use_llm": true,
  "use_web_search": false
}
```

This endpoint is the forward path for unifying global, saved-job, and analysis-preview chat around a shared assistant with contextual focus.

Supported statuses:

- `discovered`
- `interested`
- `applied`
- `interviewing`
- `rejected`
- `offer`

## Project structure

```text
app/
  main.py                  FastAPI entry point
  agents/
    coordinator.py         Main workflow orchestration
  db/
    models.py              Application data models
    repository.py          SQLite persistence layer
  memory/
    profile.example.yaml   Public profile template
    profile_store.py       Profile loading logic
  static/
    index.html             Current simple frontend UI
    styles.css
    app.js
  tools/
    job_parser.py          Deterministic job extraction
    scoring.py             Profile-aware fit scoring
frontend/
  src/
    App.tsx                CareerPilot workbench shell and screens
    api.ts                 Typed API client for FastAPI routes
    types.ts               Frontend response/request types
  package.json             React/Vite/Tailwind dependencies
docs/
  architecture.md
  evaluation.md
  learning_guide.md
  product_spec.md
tests/
  test_job_analysis.py
  test_job_analysis_evals.py
evals/
  job_analysis/cases.yaml   Job-analysis quality eval fixtures
  profiles/                 Frozen eval profiles
```

## Privacy model

This is a local-first app.

Ignored local files include:

- `.venv/`
- `data/`
- `*.sqlite3`
- `app/memory/profile.local.yaml`
- `app/memory/profile.yaml`
- `.env`

Before pushing to GitHub, check:

```bash
git status --short --ignored
```

Personal files should appear as ignored, not staged.

## Development commands

Run tests:

```bash
pytest
```

Run the server:

```bash
uvicorn app.main:app --reload
```

Install after dependency changes:

```bash
pip install -e ".[dev]"
```

Run job-analysis evals:

```bash
careerpilot-eval
```

Run evals with LLM parsing/scoring/guidance:

```bash
careerpilot-eval --llm --json
```

The eval harness uses frozen fixtures under `evals/` so prompt and scoring changes can be checked against stable product expectations. See [Evaluation Strategy](docs/evaluation.md).

Generate/import prep plans:

```http
POST /prep-plans/generate
POST /prep-plans/import
GET /prep-plans
PATCH /prep-plans/{plan_id}/days/{day}/tasks/{task_index}
```

Generate a targeted resume PDF:

```http
POST /resumes/generate
```

## Learning path

This repo is also a learning project for building production-style agentic applications.

Start with:

- [Project Roadmap](docs/project_roadmap.md): top-level phases, milestones, decisions, and long-term direction.
- [Learning Guide](docs/learning_guide.md): design patterns, code structure, and what to build next.
- [Architecture](docs/architecture.md): current components and future system direction.
- [Evaluation Strategy](docs/evaluation.md): job-analysis eval harness, fixture design, and quality gates.
- [Product Spec](docs/product_spec.md): MVP scope and product boundaries.
- [Job Fetching Tradeoffs](docs/job_fetching_tradeoffs.md): plain HTTP fetch vs browser automation vs APIs.
- [Analysis Chat Plan](docs/analysis_chat_plan.md): follow-up chat, local chat memory, and optional OpenAI web search.
- [Target Company Ingestion Plan](docs/target_company_ingestion_plan.md): watchlist-based discovery, connectors, deduplication, and future cron workflow.
- [Self-Evolving Extraction](docs/self_evolving_extraction.md): local selector learning, safety boundaries, token savings, and the future analysis-cache design.
- [Agent Workflow Runtime Plan](docs/workflow_runtime_plan.md): staged roadmap for DAG execution, cache reuse, model routing, budgets, retries, evaluation, approvals, tracing, and a later LangGraph comparison.

## Roadmap

Planned next steps:

- React/TypeScript workbench UI migration
- job-scoped follow-up chat
- optional OpenAI web search for chat and interview prep
- profile update proposals with confirmation
- resume upload and tailoring
- ranking evaluation cases
- tracing and structured logs
- Docker support
- Postgres or pgvector option
- agent orchestration with LangGraph or OpenAI Agents SDK
