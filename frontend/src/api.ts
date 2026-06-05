import type {
  AnalyzeJobRequest,
  AnalysisChatRequest,
  AnalysisFeedbackRequest,
  AnalysisFeedbackResponse,
  AssistantChatRequest,
  AssistantChatResponse,
  ApplicationStatus,
  AgentTask,
  BackgroundJobIngestRequest,
  FetchJobRequest,
  GlobalChatMessage,
  GlobalChatRequest,
  GlobalChatResponse,
  GlobalChatSession,
  JobAnalysisResponse,
  JobChatMessage,
  JobChatRequest,
  JobChatResponse,
  JobDetail,
  JobRecord,
  ProfileApplyRequest,
  ProfileApplyResponse,
  ProfileProposalRefineRequest,
  ProfileProposalRefineResponse,
  ProfileResponse,
  PrepPlan,
  PrepPlanGenerateRequest,
  PrepPlanImportRequest,
  ResumeExtractRequest,
  ResumeExtractResponse,
  ResumeGenerateRequest,
  SaveAnalyzedJobRequest,
  UpdateJobAnalysisRequest
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers
      }
    });
  } catch (error) {
    throw new Error(`Could not reach the CareerPilot backend. Make sure FastAPI is running on http://127.0.0.1:8000. ${formatUnknownError(error)}`);
  }

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

async function getErrorMessage(response: Response): Promise<string> {
  const contentType = response.headers.get("Content-Type") || "";
  if (contentType.includes("application/json")) {
    const data = (await response.json()) as { detail?: unknown };
    const message = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    return message || `Request failed with HTTP ${response.status}.`;
  }
  const text = await response.text();
  return text || `Request failed with HTTP ${response.status}.`;
}

export function formatUnknownError(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  if (typeof error === "string" && error.trim()) {
    return error;
  }
  return "No additional error details were provided.";
}

export function analyzeJob(body: AnalyzeJobRequest): Promise<JobAnalysisResponse> {
  return request<JobAnalysisResponse>("/jobs/analyze", {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function fetchAndAnalyzeJob(body: FetchJobRequest): Promise<JobAnalysisResponse> {
  return request<JobAnalysisResponse>("/jobs/fetch-and-analyze", {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function startBackgroundJobIngest(body: BackgroundJobIngestRequest): Promise<AgentTask> {
  return request<AgentTask>("/jobs/background-fetch-and-save", {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function getBackgroundJobIngest(taskId: string): Promise<AgentTask> {
  return request<AgentTask>(`/jobs/background-tasks/${encodeURIComponent(taskId)}`);
}

export function saveAnalyzedJob(body: SaveAnalyzedJobRequest): Promise<JobRecord> {
  return request<JobRecord>("/jobs/save-analysis", {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function updateJobAnalysis(jobId: number, body: UpdateJobAnalysisRequest): Promise<JobRecord> {
  return request<JobRecord>(`/jobs/${jobId}/analysis`, {
    method: "PATCH",
    body: JSON.stringify(body)
  });
}

export function saveAnalysisFeedback(body: AnalysisFeedbackRequest): Promise<AnalysisFeedbackResponse> {
  return request<AnalysisFeedbackResponse>("/jobs/analysis/feedback", {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function sendAnalysisChat(body: AnalysisChatRequest): Promise<JobChatResponse> {
  return request<JobChatResponse>("/jobs/analysis/chat", {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function sendAssistantChat(body: AssistantChatRequest): Promise<AssistantChatResponse> {
  return request<AssistantChatResponse>("/assistant/chat", {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function listJobs(): Promise<JobRecord[]> {
  return request<JobRecord[]>("/jobs");
}

export function getJob(jobId: number): Promise<JobDetail> {
  return request<JobDetail>(`/jobs/${jobId}`);
}

export function regenerateJobAnalysis(jobId: number): Promise<AgentTask> {
  return request<AgentTask>(`/jobs/${jobId}/regenerate-analysis`, {
    method: "POST"
  });
}

export function updateJobStatus(jobId: number, status: ApplicationStatus): Promise<JobRecord> {
  return request<JobRecord>(`/jobs/${jobId}/status?status=${encodeURIComponent(status)}`, {
    method: "PATCH"
  });
}

export function deleteJob(jobId: number): Promise<void> {
  return request<void>(`/jobs/${jobId}`, {
    method: "DELETE"
  });
}

export function listJobChat(jobId: number): Promise<JobChatMessage[]> {
  return request<JobChatMessage[]>(`/jobs/${jobId}/chat`);
}

export function sendJobChat(jobId: number, body: JobChatRequest): Promise<JobChatResponse> {
  return request<JobChatResponse>(`/jobs/${jobId}/chat`, {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function clearJobChat(jobId: number): Promise<void> {
  return request<void>(`/jobs/${jobId}/chat`, {
    method: "DELETE"
  });
}

export type JobChatStreamEvent =
  | { type: "status"; message: string }
  | { type: "chunk"; text: string }
  | {
      type: "done";
      message?: JobChatMessage;
      responder_used?: string;
      responder_warning?: string | null;
      used_web_search?: boolean;
      citations?: Array<{ title: string; url: string }>;
    }
  | { type: "error"; message: string };

export async function streamJobChat(
  jobId: number,
  body: JobChatRequest,
  onEvent: (event: JobChatStreamEvent) => void
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/jobs/${jobId}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  } catch (error) {
    throw new Error(`Could not reach the CareerPilot backend. Make sure FastAPI is running on http://127.0.0.1:8000. ${formatUnknownError(error)}`);
  }

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }
  if (!response.body) {
    throw new Error("Streaming response did not include a readable body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        continue;
      }
      onEvent(JSON.parse(trimmed) as JobChatStreamEvent);
    }
  }

  const remaining = buffer.trim();
  if (remaining) {
    onEvent(JSON.parse(remaining) as JobChatStreamEvent);
  }
}

export function listGlobalChat(): Promise<GlobalChatMessage[]> {
  return request<GlobalChatMessage[]>("/chat");
}

export function listGlobalChatSessions(): Promise<GlobalChatSession[]> {
  return request<GlobalChatSession[]>("/chat/sessions");
}

export function createGlobalChatSession(title = "New chat"): Promise<GlobalChatSession> {
  return request<GlobalChatSession>("/chat/sessions", {
    method: "POST",
    body: JSON.stringify({ title })
  });
}

export function deleteGlobalChatSession(sessionId: number): Promise<void> {
  return request<void>(`/chat/sessions/${sessionId}`, {
    method: "DELETE"
  });
}

export function listGlobalChatForSession(sessionId: number): Promise<GlobalChatMessage[]> {
  return request<GlobalChatMessage[]>(`/chat?session_id=${encodeURIComponent(sessionId)}`);
}

export function sendGlobalChat(body: GlobalChatRequest): Promise<GlobalChatResponse> {
  return request<GlobalChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function clearGlobalChat(): Promise<void> {
  return request<void>("/chat", {
    method: "DELETE"
  });
}

export function clearGlobalChatSession(sessionId: number): Promise<void> {
  return request<void>(`/chat?session_id=${encodeURIComponent(sessionId)}`, {
    method: "DELETE"
  });
}

export function getProfile(): Promise<ProfileResponse> {
  return request<ProfileResponse>("/profile");
}

export function extractResumeProfile(body: ResumeExtractRequest): Promise<ResumeExtractResponse> {
  return request<ResumeExtractResponse>("/profile/resume/extract", {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function applyProfileUpdates(body: ProfileApplyRequest): Promise<ProfileApplyResponse> {
  return request<ProfileApplyResponse>("/profile/apply", {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function refineProfileProposal(body: ProfileProposalRefineRequest): Promise<ProfileProposalRefineResponse> {
  return request<ProfileProposalRefineResponse>("/profile/proposals/refine", {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function listPrepPlans(): Promise<PrepPlan[]> {
  return request<PrepPlan[]>("/prep-plans");
}

export function generatePrepPlan(body: PrepPlanGenerateRequest): Promise<PrepPlan> {
  return request<PrepPlan>("/prep-plans/generate", {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function importPrepPlan(body: PrepPlanImportRequest): Promise<PrepPlan> {
  return request<PrepPlan>("/prep-plans/import", {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function updatePrepTask(planId: number, day: number, taskIndex: number, completed: boolean): Promise<PrepPlan> {
  return request<PrepPlan>(`/prep-plans/${planId}/days/${day}/tasks/${taskIndex}`, {
    method: "PATCH",
    body: JSON.stringify({ completed })
  });
}

export async function generateResumePdf(body: ResumeGenerateRequest): Promise<Blob> {
  const response = await fetch("/resumes/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }
  return response.blob();
}
