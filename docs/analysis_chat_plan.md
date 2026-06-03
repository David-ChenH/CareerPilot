# Analysis Chat Plan

This plan describes the interactive chat experience: job-scoped chat for a saved job analysis and global chat for broader planning across the local job-search workspace.

## Goal

Let the user move from a static analysis result to an interactive coaching workflow:

```text
saved job analysis
  -> ask follow-up question
  -> answer using profile + job + analysis
  -> optionally use web search for current external context
  -> preserve useful local chat history
```

This should help with:

- understanding role fit
- deciding whether to apply
- preparing for interviews
- tailoring resume emphasis
- identifying learning priorities
- researching recent company context

The global assistant adds a second workflow:

```text
profile + saved jobs + application statuses
  -> broad planning question
  -> answer using local workspace state
  -> optionally use web search for current external context
  -> preserve global chat history locally
```

## Why this comes before scan automation

Target-company scanning finds more jobs, but the user still needs to understand each role deeply. Improving analysis and follow-up chat first makes every later discovery feature more valuable.

The product should first become excellent at:

```text
one job -> deep understanding -> prep/application guidance
```

Then later:

```text
many jobs -> ranked queue -> deep understanding
```

## Chat context

Job-scoped chat should be scoped to a saved job.

Context sent to the model:

- user profile
- persisted parsed job fields
- persisted LLM fit result
- persisted guidance result
- source URL
- application status
- prior chat messages for that job

Context not sent by default:

- unrelated jobs
- entire application history
- private files not needed for the answer

Global chat uses a different context boundary:

- user profile
- saved job summaries
- fit scores and application statuses
- persisted analysis summaries, gaps, and prep-plan highlights when available
- recent global chat messages

Global chat does not send full job descriptions by default. This keeps context compact and focuses the assistant on planning, comparison, and next actions.

## Suggested API

Job-scoped chat:

```http
POST /jobs/{job_id}/chat
POST /jobs/{job_id}/chat/stream
```

Request:

```json
{
  "message": "What should I study first for this role?",
  "use_llm": true,
  "use_web_search": false
}
```

Global assistant:

```http
GET /chat/sessions
POST /chat/sessions
DELETE /chat/sessions/{session_id}
GET /chat
POST /chat
```

Global request:

```json
{
  "message": "Rank my saved jobs for AI platform transition.",
  "session_id": 1,
  "use_llm": true,
  "use_web_search": false
}
```

Response:

```json
{
  "answer": "...",
  "session": {
    "id": 1,
    "title": "Rank my saved jobs for AI",
    "created_at": "...",
    "updated_at": "..."
  },
  "used_web_search": false,
  "citations": [],
  "responder_used": "llm",
  "messages": []
}
```

Streaming response:

The streaming endpoint returns newline-delimited JSON events:

```json
{"type": "status", "message": "Loading saved job context"}
{"type": "status", "message": "Generating answer"}
{"type": "chunk", "text": "Start with Kubernetes..."}
{"type": "done", "message": {"role": "assistant"}}
```

The UI should show progress states, not hidden chain-of-thought. This gives the user confidence that the assistant is working while preserving the boundary between observable workflow state and private model reasoning.

## Storage

Store chat history locally, likely in SQLite:

```text
job_chat_messages
  id
  job_id
  role
  content
  used_web_search
  citations_json
  created_at

global_chat_messages
  id
  session_id
  role
  content
  used_web_search
  citations_json
  created_at

global_chat_sessions
  id
  title
  created_at
  updated_at
```

This keeps the chat durable without relying on remote memory. The global Assistant uses session-scoped history so broad career planning can happen in multiple threads, while job-specific chat remains attached to a saved application.

## Web search mode

OpenAI API web search should be an optional mode, not always on.

Status: initial implementation complete.

Implementation notes:

- The React chat panel exposes an explicit `Use web search` checkbox.
- The backend calls the OpenAI Responses API with the built-in `web_search` tool only when that flag is true.
- Web-search answers store `used_web_search` and `citations` on the assistant message.
- Source links are shown in the UI because web-derived claims need to be inspectable.
- The default web-search model is configured separately with `JOB_AGENT_WEB_SEARCH_MODEL`.

Use web search for:

- recent company news
- recent interview reports
- public product announcements
- current hiring or org context
- role/company prep research

Do not need web search for:

- explaining the saved job description
- comparing the job to the local profile
- resume emphasis based on local experience
- application status questions

This keeps answers faster and cheaper when current web data is not needed.

## Memory update boundary

Chat should not silently update `profile.local.yaml`.

If the user says something like:

```text
Actually, I have 3 years of Java experience.
```

The app should propose a memory update:

```yaml
technical_strengths:
  - "Java"
```

Then require explicit confirmation before writing it.

## First implementation milestone

Build the smallest useful version:

1. Add chat message model and repository methods.
2. Add `POST /jobs/{job_id}/chat`.
3. Build answer from local profile + saved job + analysis.
4. Store user/assistant messages locally.
5. Add a simple chat panel to the UI for selected/saved jobs.
6. Keep web search off for the first pass.

Status: complete.

Streaming/refined chat milestone:

1. Add job-scoped streaming endpoint.
   - Status: complete.
2. Show progress states while the backend works.
   - Status: complete.
3. Stream answer text into the job chat panel.
   - Status: complete.
4. Move job chat to the side of the saved-application drawer.
   - Status: complete.

Global assistant milestone:

1. Add global chat table.
   - Status: complete.
2. Add `GET /chat` and `POST /chat`.
   - Status: complete.
3. Build answer from local profile + saved job summaries + global chat history.
   - Status: complete.
4. Add Assistant sidebar UI.
   - Status: complete.
5. Keep memory updates as proposed/confirmed future workflow.
   - Status: still planned.

Then add:

1. `use_web_search` flag.
   - Status: complete.
2. OpenAI web search tool.
   - Status: complete.
3. Citation display.
   - Status: complete.
4. Prep/research-specific prompt paths.
   - Status: still planned.

## Interview framing

A good explanation:

> I delayed broad job discovery and focused first on making each job analysis actionable. The chat feature turns a static score into an interactive workflow where the user can ask about fit, risks, prep plans, and resume positioning. Web search is added as an optional tool for current company or interview context, while local profile and application state remain the core memory. This separates stable local knowledge from dynamic external research.
