export type ApplicationStatus =
  | "discovered"
  | "interested"
  | "applied"
  | "interviewing"
  | "rejected"
  | "offer";

export type ParsedJob = {
  title?: string | null;
  company?: string | null;
  location?: string | null;
  seniority?: string | null;
  description: string;
  skills: string[];
  required_skills?: string[];
  preferred_skills?: string[];
  accepted_skill_alternatives?: string[];
  responsibilities?: string[];
  requirements?: string[];
  ambiguous_qualifications?: string[];
  role_focus?: string[];
  compensation?: string | null;
  team_business?: string | null;
};

export type EvidenceItem = {
  claim: string;
  evidence_from_job?: string | null;
  profile_signal?: string | null;
  severity?: string | null;
  confidence?: string | null;
  source?: string | null;
};

export type JobFit = {
  score: number;
  priority: string;
  strong_matches: string[];
  gaps: string[];
  growth_areas: string[];
  concerns: string[];
  summary: string;
  recommendation?: string | null;
  transition_notes: string[];
  evidence?: Record<string, EvidenceItem[]>;
};

export type JobApplicationGuidance = {
  apply_reasoning: string[];
  prep_plan: string[];
  resume_guidance: string[];
  learning_plan: string[];
  interview_focus: string[];
  evidence?: Record<string, EvidenceItem[]>;
};

export type JobRecord = {
  id: number;
  source_url?: string | null;
  title?: string | null;
  company?: string | null;
  location?: string | null;
  description: string;
  skills: string[];
  fit_score: number;
  priority: string;
  status: ApplicationStatus;
  application_type: "internal_transfer" | "external_application" | "unknown";
  analysis?: JobAnalysisResponse | null;
};

export type JobAnalysisResponse = {
  extracted_posting?: ExtractedJobPosting | null;
  parsed_job: ParsedJob;
  fit: JobFit;
  parser_used: string;
  parser_warning?: string | null;
  scorer_used: string;
  guidance: JobApplicationGuidance;
  guidance_used: string;
  guidance_warning?: string | null;
  saved_job?: JobRecord | null;
  resume_emphasis: string[];
  prep_topics: string[];
};

export type JobDetail = {
  job: JobRecord;
  analysis?: JobAnalysisResponse | null;
};

export type ChatRole = "user" | "assistant";

export type JobChatMessage = {
  id: number;
  job_id: number;
  role: ChatRole;
  content: string;
  used_web_search: boolean;
  citations: Array<{ title: string; url: string }>;
  created_at?: string | null;
};

export type JobChatRequest = {
  message: string;
  use_llm: boolean;
  use_web_search: boolean;
};

export type JobChatResponse = {
  answer: string;
  messages: JobChatMessage[];
  responder_used: string;
  responder_warning?: string | null;
  used_web_search: boolean;
  citations: Array<{ title: string; url: string }>;
};

export type AnalysisChatRequest = {
  analysis: JobAnalysisResponse;
  message: string;
  history: JobChatMessage[];
  source_url?: string | null;
  use_llm: boolean;
  use_web_search: boolean;
};

export type AssistantFocus =
  | { type: "global" }
  | { type: "saved_job"; job_id: number }
  | { type: "analysis_preview"; analysis: JobAnalysisResponse; source_url?: string | null };

export type AssistantChatRequest = {
  message: string;
  focus: AssistantFocus;
  session_id?: number | null;
  history: JobChatMessage[];
  use_llm: boolean;
  use_web_search: boolean;
};

export type AssistantChatResponse = {
  answer: string;
  focus: AssistantFocus;
  messages: JobChatMessage[];
  session?: GlobalChatSession | null;
  responder_used: string;
  responder_warning?: string | null;
  used_web_search: boolean;
  citations: Array<{ title: string; url: string }>;
};

export type GlobalChatMessage = Omit<JobChatMessage, "job_id">;

export type GlobalChatSession = {
  id: number;
  title: string;
  created_at?: string | null;
  updated_at?: string | null;
};

export type GlobalChatRequest = {
  message: string;
  session_id?: number | null;
  use_llm: boolean;
  use_web_search: boolean;
};

export type GlobalChatResponse = {
  answer: string;
  session: GlobalChatSession;
  messages: GlobalChatMessage[];
  responder_used: string;
  responder_warning?: string | null;
  used_web_search: boolean;
  citations: Array<{ title: string; url: string }>;
  actions: AgentTask[];
};

export type AnalyzeJobRequest = {
  description: string;
  source_url?: string | null;
  save: boolean;
  use_llm: boolean;
  use_llm_guidance: boolean;
};

export type FetchJobRequest = {
  url: string;
  save: boolean;
  use_browser_fallback: boolean;
  use_llm: boolean;
  use_llm_guidance: boolean;
};

export type BackgroundJobIngestRequest = {
  url: string;
  save: boolean;
  use_browser_fallback: boolean;
  use_llm: boolean;
  use_llm_guidance: boolean;
};

export type ExtractedSection = {
  heading?: string | null;
  items: string[];
  source: string;
  order: number;
};

export type ExtractedJobPosting = {
  metadata: Record<string, string | null>;
  sections: ExtractedSection[];
  extraction_source: string;
  warnings: string[];
};

export type AgentTaskStep = {
  name: string;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  summary?: string | null;
  error?: string | null;
};

export type WorkflowGraphNode = {
  id: string;
  label: string;
  tool: string;
  description: string;
  status: string;
};

export type WorkflowGraphEdge = {
  source: string;
  target: string;
};

export type WorkflowGraph = {
  workflow_id: string;
  workflow_version: number;
  nodes: WorkflowGraphNode[];
  edges: WorkflowGraphEdge[];
};

export type WorkflowTraceEvent = {
  task_id: string;
  event: string;
  timestamp: string;
  detail?: string | null;
};

export type WorkflowRunArtifact = {
  id: string;
  workflow_id: string;
  workflow_version: number;
  status: string;
  trace_events: WorkflowTraceEvent[];
};

export type AgentTask = {
  id: string;
  type: "job_link_ingest";
  status: "queued" | "running" | "needs_input" | "ready_for_review" | "approved" | "completed" | "failed";
  input: Record<string, unknown>;
  steps: AgentTaskStep[];
  artifacts: {
    source_url?: string | null;
    page_title?: string | null;
    extraction_source?: string;
    extracted_posting?: ExtractedJobPosting | null;
    description_length?: number;
    analysis?: JobAnalysisResponse;
    saved_job?: JobRecord;
    workflow_graph?: WorkflowGraph;
    workflow_run?: WorkflowRunArtifact;
  };
  error?: string | null;
  created_at: string;
  updated_at: string;
};

export type SaveAnalyzedJobRequest = {
  analysis: JobAnalysisResponse;
  source_url?: string | null;
};

export type UpdateJobAnalysisRequest = {
  analysis: JobAnalysisResponse;
  source_url?: string | null;
  reason?: string | null;
};

export type AnalysisFeedbackType = "accurate" | "missing_gap" | "wrong_concern" | "too_generic" | "other";

export type AnalysisFeedbackRequest = {
  analysis: JobAnalysisResponse;
  feedback_type: AnalysisFeedbackType;
  note?: string | null;
  source_url?: string | null;
};

export type AnalysisFeedbackResponse = {
  id: string;
  created_at: string;
  feedback_type: AnalysisFeedbackType;
  summary: string;
};

export type ProfileResponse = {
  profile: Record<string, unknown>;
  source: string;
};

export type ResumeExtractRequest = {
  filename?: string | null;
  content: string;
};

export type ResumeExtractResponse = {
  proposal_id?: number | null;
  filename?: string | null;
  proposed_updates: Record<string, string[]>;
  summary: string;
};

export type ProfileApplyRequest = {
  proposal_id?: number | null;
  proposed_updates: Record<string, string[]>;
  source?: string;
};

export type ProfileApplyResponse = {
  profile: Record<string, unknown>;
  source: string;
  applied_updates: Record<string, string[]>;
  summary: string;
};

export type ProfileProposalRefineRequest = {
  proposal_id?: number | null;
  proposed_updates: Record<string, string[]>;
  message: string;
  use_llm: boolean;
};

export type ProfileProposalRefineResponse = {
  proposal_id?: number | null;
  answer: string;
  proposed_updates: Record<string, string[]>;
  responder_used: string;
  responder_warning?: string | null;
};

export type PrepTask = {
  title: string;
  category: string;
  minutes: number;
  completed: boolean;
};

export type PrepDay = {
  day: number;
  title: string;
  tasks: PrepTask[];
};

export type PrepPlan = {
  id: number;
  title: string;
  source: string;
  timeline_days: number;
  hours_per_day: number;
  days: PrepDay[];
  schema_version: number;
  revision: number;
  created_at?: string | null;
  updated_at?: string | null;
};

export type PrepPlanGenerateRequest = {
  timeline_days: number;
  hours_per_day: number;
  focus?: string | null;
  job_id?: number | null;
  use_llm: boolean;
};

export type PrepPlanImportRequest = {
  title: string;
  content: string;
};

export type ResumeGenerateRequest = {
  role_title: string;
  company?: string | null;
  job_id?: number | null;
  notes?: string | null;
  use_llm: boolean;
};
