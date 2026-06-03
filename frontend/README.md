# CareerPilot Frontend Workbench

React/Vite frontend for the local-first CareerPilot app.

## Why this exists

The initial FastAPI-served static UI was useful for validating the backend workflow. The product is now moving toward richer stateful interactions:

- selected saved-job detail
- persisted analysis review
- future job-scoped chat
- optional web-search controls
- better loading and error states

React gives us a cleaner place to model that UI state while keeping the agent workflow in the FastAPI backend.

## Runtime

Use Node 24 LTS.

The repo declares this with:

- `../.nvmrc`
- `../.node-version`
- `package.json` `engines.node`

## Run locally

Start the backend from the repo root:

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

Start the frontend from this directory:

```bash
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

Vite proxies API requests to the backend on `http://127.0.0.1:8000`.

## Current workflow

The workbench now uses a sidebar workspace:

- `Dashboard`: summary and next actions.
- `Analyze Job`: job link or pasted description analysis.
- `Applications`: saved jobs and application status.
- `Assistant`: planned global assistant for cross-job questions.
- `Assistant`: global assistant for comparing saved jobs, planning prep, and broader career/job-search questions.
- `Profile`: current profile memory and resume text extraction.
- `Settings`: planned local profile and model/API controls.

`Analyze Job` separates job input into two modes:

- `Job Link`: paste a URL, then click `Fetch & Analyze`. The app fetches the page, analyzes it, and saves it if tracking is enabled. The raw fetched text stays hidden unless `View fetched text` is opened for debugging.
- `Paste Text`: paste the description manually, optionally include a source URL, then click `Analyze`.

This keeps the main path simple while preserving a manual fallback for job sites that block automated fetching.

The `Assistant` page is not tied to a single job. It uses the local profile, saved job summaries, application statuses, and global chat history. It is the right place for questions like ranking saved jobs, comparing gaps, or building a prep plan.

Saved jobs also include an `Ask About This Job` panel. Questions are sent to the FastAPI backend with the selected job, saved analysis, local profile, and local chat history as context.

Use the `Use web search` checkbox only for current external context, such as recent company news, product announcements, or interview-prep research. When web search is used, cited source links are displayed under the assistant response and stored locally with the chat message.

Saved job detail opens in a drawer from `Applications`. This keeps the main tracker uncluttered while preserving access to fit details, prep guidance, and job-scoped chat.

The drawer uses a split layout on wider screens:

- left side: saved analysis, guidance, gaps, and role facts
- right side: sticky job-scoped chat

Job-scoped chat shows progress states and streams answer text while the backend is working. The UI does not expose hidden model chain-of-thought; it shows operational progress such as loading context, reading saved analysis, optional web search preparation, and answer generation.

Chat history is not shown by default. Each assistant panel starts as a fresh session and offers `Load history` / `Clear history` controls. This keeps old conversations from crowding the primary workflow while preserving local persistence.

The `Profile` area shows what CareerPilot currently knows from the local profile file. It also includes a resume portal for Markdown or plain-text resumes. The portal extracts proposed updates for review but does not write to profile memory yet; saving profile updates should remain an explicit confirmation flow.

## Structure

```text
src/
  App.tsx       Workbench shell and screens
  api.ts        Typed FastAPI client
  types.ts      Frontend request/response contracts
  utils.ts      Small display helpers
  index.css     Tailwind component styles
```

## Design intent

This is a workbench UI, not a marketing site. The layout should make job analysis, saved-job review, and future chat workflows easy to demo without hiding the backend/agent architecture.
