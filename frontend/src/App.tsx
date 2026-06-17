import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertCircle,
  Bot,
  BookOpenCheck,
  BriefcaseBusiness,
  CalendarCheck,
  CheckCircle2,
  Clock,
  Clipboard,
  Code2,
  Download,
  Eye,
  EyeOff,
  ExternalLink,
  FileSearch,
  FileText,
  Link,
  LayoutDashboard,
  Loader2,
  MessageCircle,
  RefreshCw,
  Send,
  Settings,
  Trash2,
  Users,
  X
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";

import { Badge, DataPill, EmptyState, MetricCard, PageHeader, Panel, SectionTitle } from "./components/ui";
import {
  analyzeJob,
  applyProfileUpdates,
  clearGlobalChatSession,
  clearJobChat,
  deleteJob,
  deleteGlobalChatSession,
  extractResumeProfile,
  formatUnknownError,
  getBackgroundJobIngest,
  getJob,
  getProfile,
  createLeetCodeProblem,
  deleteLeetCodeProblem,
  generatePrepPlan,
  generateResumePdf,
  importPrepPlan,
  listJobChat,
  listGlobalChatForSession,
  listGlobalChatSessions,
  listJobs,
  listLeetCodeProblems,
  listPrepPlans,
  refineProfileProposal,
  saveAnalysisFeedback,
  saveAnalyzedJob,
  sendAssistantChat,
  sendJobChat,
  sendGlobalChat,
  startBackgroundJobIngest,
  streamJobChat,
  updateLeetCodeProblem,
  updatePrepTask,
  updateJobAnalysis,
  updateJobStatus
} from "./api";
import type {
  ApplicationStatus,
  AnalysisFeedbackType,
  AgentTask,
  AgentTaskStep,
  EvidenceItem,
  GlobalChatMessage,
  GlobalChatSession,
  JobAnalysisResponse,
  JobApplicationGuidance,
  JobChatMessage,
  JobDetail,
  JobFit,
  JobRecord,
  LeetCodeProblem,
  LeetCodeProblemRequest,
  LeetCodeStatus,
  ParsedJob,
  PrepPlan,
  ProfileProposalRefineResponse,
  ResumeExtractResponse
} from "./types";
import { buildTrackerSummary, titleCase } from "./utils";

type InputMode = "link" | "paste";
type AppView = "dashboard" | "analyze" | "applications" | "prep" | "leetcode" | "resume" | "assistant" | "profile" | "settings";
type PrepSeed = { nonce: number; focus: string; jobId?: number | null };
type ResumeSeed = { nonce: number; roleTitle: string; company?: string | null; jobId?: number | null; notes: string };
type AnalysisRefreshContext = { jobId: number; title: string; sourceUrl: string };

const statuses: ApplicationStatus[] = [
  "discovered",
  "interested",
  "applied",
  "interviewing",
  "rejected",
  "offer"
];
const leetcodeStatuses: LeetCodeStatus[] = ["todo", "in_progress", "solved", "review"];

export function App() {
  const queryClient = useQueryClient();
  const [activeView, setActiveView] = useState<AppView>("dashboard");
  const [inputMode, setInputMode] = useState<InputMode>("link");
  const [jobUrl, setJobUrl] = useState("");
  const [description, setDescription] = useState("");
  const [showFetchedText, setShowFetchedText] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  const [analysis, setAnalysis] = useState<JobAnalysisResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [prepSeed, setPrepSeed] = useState<PrepSeed | null>(null);
  const [resumeSeed, setResumeSeed] = useState<ResumeSeed | null>(null);
  const [backgroundTaskId, setBackgroundTaskId] = useState<string | null>(null);
  const [regeneratingJobId, setRegeneratingJobId] = useState<number | null>(null);
  const [analysisRefreshContext, setAnalysisRefreshContext] = useState<AnalysisRefreshContext | null>(null);

  const jobsQuery = useQuery({
    queryKey: ["jobs"],
    queryFn: listJobs
  });

  const jobDetailQuery = useQuery({
    queryKey: ["jobs", selectedJobId],
    queryFn: () => getJob(selectedJobId as number),
    enabled: selectedJobId !== null
  });

  const backgroundTaskQuery = useQuery({
    queryKey: ["background-job-ingest", backgroundTaskId],
    queryFn: () => getBackgroundJobIngest(backgroundTaskId as string),
    enabled: backgroundTaskId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 1500;
    }
  });

  const analyzeMutation = useMutation({
    mutationFn: analyzeJob,
    onSuccess: async (result) => {
      setAnalysis(result);
      setNotice("Analysis complete.");
      if (result.parsed_job.description) {
        setDescription(result.parsed_job.description);
      }
    }
  });

  const backgroundPreviewMutation = useMutation({
    mutationFn: startBackgroundJobIngest,
    onSuccess: (task) => {
      setBackgroundTaskId(task.id);
      setNotice("Analysis started. CareerPilot will show workflow progress while it fetches and evaluates the link.");
    }
  });

  const backgroundIngestMutation = useMutation({
    mutationFn: startBackgroundJobIngest,
    onSuccess: (task) => {
      setBackgroundTaskId(task.id);
      setNotice("Background save started. You can keep using the app while CareerPilot analyzes the link.");
    }
  });

  const saveAnalysisMutation = useMutation({
    mutationFn: (currentAnalysis: JobAnalysisResponse) =>
      saveAnalyzedJob({
        analysis: currentAnalysis,
        source_url: jobUrl.trim() || null
      }),
    onSuccess: async (savedJob) => {
      setAnalysis((current) => (current ? { ...current, saved_job: savedJob } : current));
      setSelectedJobId(savedJob.id);
      setNotice("Saved job to tracker.");
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      await queryClient.invalidateQueries({ queryKey: ["jobs", savedJob.id] });
    }
  });

  const applyAnalysisMutation = useMutation({
    mutationFn: ({ jobId, currentAnalysis, sourceUrl }: { jobId: number; currentAnalysis: JobAnalysisResponse; sourceUrl: string | null }) =>
      updateJobAnalysis(jobId, {
        analysis: currentAnalysis,
        source_url: sourceUrl,
        reason: "user_confirmed_refresh"
      }),
    onSuccess: async (savedJob) => {
      setAnalysis((current) => (current ? { ...current, saved_job: savedJob } : current));
      setSelectedJobId(savedJob.id);
      setAnalysisRefreshContext(null);
      setNotice("Saved job analysis updated.");
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      await queryClient.invalidateQueries({ queryKey: ["jobs", savedJob.id] });
      setActiveView("applications");
    }
  });

  const statusMutation = useMutation({
    mutationFn: ({ jobId, status }: { jobId: number; status: ApplicationStatus }) =>
      updateJobStatus(jobId, status),
    onSuccess: async (job) => {
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      await queryClient.invalidateQueries({ queryKey: ["jobs", job.id] });
    }
  });

  const deleteMutation = useMutation({
    mutationFn: deleteJob,
    onSuccess: async (_, deletedJobId) => {
      if (selectedJobId === deletedJobId) {
        setSelectedJobId(null);
      }
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
    }
  });

  useEffect(() => {
    const task = backgroundTaskQuery.data;
    if (!task || task.status !== "completed") {
      return;
    }

    if (task.input.save === false && task.artifacts.analysis) {
      setAnalysis(task.artifacts.analysis);
      setDescription(task.artifacts.analysis.parsed_job.description);
      setShowFetchedText(false);
      setRegeneratingJobId(null);
      setNotice(analysisRefreshContext ? "Refreshed analysis preview ready. Review it before updating the saved job." : "Analysis complete.");
      return;
    }

    if (!task.artifacts.saved_job?.id) {
      return;
    }
    setNotice(`Background analysis saved: ${task.artifacts.saved_job.title || "Untitled job"}.`);
    setSelectedJobId(task.artifacts.saved_job.id);
    setRegeneratingJobId(null);
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
    queryClient.invalidateQueries({ queryKey: ["jobs", task.artifacts.saved_job.id] });
  }, [analysisRefreshContext, backgroundTaskQuery.data, queryClient]);

  useEffect(() => {
    if (backgroundTaskQuery.data?.status === "failed") {
      setRegeneratingJobId(null);
    }
  }, [backgroundTaskQuery.data?.status]);

  const activeError =
    analyzeMutation.error?.message ||
    backgroundPreviewMutation.error?.message ||
    backgroundIngestMutation.error?.message ||
    backgroundTaskQuery.error?.message ||
    saveAnalysisMutation.error?.message ||
    applyAnalysisMutation.error?.message ||
    jobsQuery.error?.message ||
    jobDetailQuery.error?.message ||
    statusMutation.error?.message ||
    deleteMutation.error?.message ||
    null;

  const isAnalyzing = analyzeMutation.isPending || backgroundPreviewMutation.isPending;

  function updateJobUrl(nextUrl: string) {
    setJobUrl(nextUrl);
    setBackgroundTaskId(null);
    setRegeneratingJobId(null);
    setAnalysisRefreshContext(null);
    setNotice(null);
    if (inputMode === "link") {
      setAnalysis(null);
      setDescription("");
      setShowFetchedText(false);
    }
  }

  function submitAnalysis() {
    setNotice(null);
    setAnalysis(null);
    const trimmed = description.trim();
    if (!trimmed) {
      setNotice("Paste a job description before analyzing.");
      return;
    }
    analyzeMutation.mutate({
      description: trimmed,
      source_url: jobUrl.trim() || null,
      save: false,
      use_llm: true,
      use_llm_guidance: true
    });
  }

  function submitFetch() {
    setNotice(null);
    setAnalysis(null);
    setBackgroundTaskId(null);
    const trimmed = jobUrl.trim();
    if (!trimmed) {
      setNotice("Paste a job link before fetching.");
      return;
    }
    backgroundPreviewMutation.mutate({
      url: trimmed,
      save: false,
      use_browser_fallback: true,
      use_llm: true,
      use_llm_guidance: true
    });
  }

  function startRefreshPreview(job: JobRecord) {
    if (!job.source_url) {
      setNotice("This saved job does not have a source link. Paste its current description into Analyze Job to refresh it.");
      return;
    }
    setInputMode("link");
    setJobUrl(job.source_url);
    setDescription("");
    setAnalysis(null);
    setShowFetchedText(false);
    setBackgroundTaskId(null);
    setSelectedJobId(null);
    setRegeneratingJobId(job.id);
    setAnalysisRefreshContext({
      jobId: job.id,
      title: job.title || "Untitled job",
      sourceUrl: job.source_url
    });
    setActiveView("analyze");
    backgroundPreviewMutation.mutate({
      url: job.source_url,
      save: false,
      use_browser_fallback: true,
      use_llm: true,
      use_llm_guidance: true
    });
  }

  function submitBackgroundSave() {
    setNotice(null);
    setBackgroundTaskId(null);
    const trimmed = jobUrl.trim();
    if (!trimmed) {
      setNotice("Paste a job link before starting a background save.");
      return;
    }
    backgroundIngestMutation.mutate({
      url: trimmed,
      save: true,
      use_browser_fallback: true,
      use_llm: true,
      use_llm_guidance: true
    });
  }

  return (
    <div className="min-h-screen bg-canvas text-ink lg:grid lg:grid-cols-[272px_1fr]">
      <AppSidebar activeView={activeView} onChange={setActiveView} />

      <div className="min-w-0">
        <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
          <div className="flex flex-col gap-3 px-5 py-4 sm:px-8 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase text-slate-500">CareerPilot Workspace</p>
              <h1 className="mt-1 text-2xl font-semibold text-slate-950">{viewTitle(activeView)}</h1>
              <p className="mt-1 text-sm text-slate-500">{viewSubtitle(activeView)}</p>
            </div>
            <a
              className="secondary-button self-start lg:self-auto"
              href="/docs"
              target="_blank"
              rel="noreferrer"
            >
              <BookOpenCheck size={18} />
              API Docs
            </a>
          </div>
        </header>

        <main className="mx-auto max-w-[1580px] px-5 py-6 sm:px-8">
          {activeView === "dashboard" ? <DashboardView jobs={jobsQuery.data ?? []} onNavigate={setActiveView} /> : null}
          {activeView === "analyze" ? (
            <AnalyzeJobView
              activeError={activeError}
              analysis={analysis}
              description={description}
              fetchPending={backgroundPreviewMutation.isPending}
              backgroundTask={backgroundTaskQuery.data ?? null}
              backgroundSavePending={backgroundIngestMutation.isPending}
              refreshContext={analysisRefreshContext}
              inputMode={inputMode}
              isAnalyzing={isAnalyzing}
              jobUrl={jobUrl}
              notice={notice}
              savePending={saveAnalysisMutation.isPending}
              applyUpdatePending={applyAnalysisMutation.isPending}
              showFetchedText={showFetchedText}
              saveAnalysis={() => {
                if (analysis) {
                  saveAnalysisMutation.mutate(analysis);
                }
              }}
              applyAnalysisUpdate={() => {
                if (analysis && analysisRefreshContext) {
                  applyAnalysisMutation.mutate({
                    jobId: analysisRefreshContext.jobId,
                    currentAnalysis: analysis,
                    sourceUrl: analysisRefreshContext.sourceUrl
                  });
                }
              }}
              submitAnalysis={submitAnalysis}
              submitBackgroundSave={submitBackgroundSave}
              submitFetch={submitFetch}
              setDescription={setDescription}
              setInputMode={setInputMode}
              setJobUrl={updateJobUrl}
              setShowFetchedText={setShowFetchedText}
              analyzePending={analyzeMutation.isPending}
              onCreatePrepPlan={(currentAnalysis) => {
                setPrepSeed({
                  nonce: Date.now(),
                  focus: buildPrepFocus(currentAnalysis),
                  jobId: currentAnalysis.saved_job?.id ?? null
                });
                setActiveView("prep");
              }}
              onGenerateResume={(currentAnalysis) => {
                setResumeSeed({
                  nonce: Date.now(),
                  roleTitle: currentAnalysis.parsed_job.title || "Target role",
                  company: currentAnalysis.parsed_job.company,
                  jobId: currentAnalysis.saved_job?.id ?? null,
                  notes: buildResumeNotes(currentAnalysis)
                });
                setActiveView("resume");
              }}
            />
          ) : null}
          {activeView === "applications" ? (
            <JobTracker
              jobs={jobsQuery.data ?? []}
              isLoading={jobsQuery.isLoading}
              selectedJobId={selectedJobId}
              onRefresh={() => queryClient.invalidateQueries({ queryKey: ["jobs"] })}
              onSelect={setSelectedJobId}
              onStatusChange={(jobId, status) => statusMutation.mutate({ jobId, status })}
              onDelete={(jobId) => deleteMutation.mutate(jobId)}
            />
          ) : null}
          {activeView === "prep" ? <PrepPlanView jobs={jobsQuery.data ?? []} seed={prepSeed} /> : null}
          {activeView === "leetcode" ? <LeetCodeDashboard /> : null}
          {activeView === "resume" ? <ResumeView jobs={jobsQuery.data ?? []} seed={resumeSeed} /> : null}
          {activeView === "assistant" ? <GlobalAssistantView /> : null}
          {activeView === "profile" ? <ProfileView /> : null}
          {activeView === "settings" ? <PlaceholderView icon={<Settings size={22} />} title="Settings" body="This area will expose model/API configuration and local workflow controls without mixing those controls into the main profile or application views." /> : null}
        </main>
      </div>

      {activeView === "applications" && selectedJobId !== null ? (
        <JobDetailDrawer
          detail={jobDetailQuery.data}
          isLoading={jobDetailQuery.isLoading}
          isRegenerating={regeneratingJobId === selectedJobId}
          onRegenerate={startRefreshPreview}
          onClose={() => setSelectedJobId(null)}
        />
      ) : null}
    </div>
  );
}

function AppSidebar({ activeView, onChange }: { activeView: AppView; onChange: (view: AppView) => void }) {
  const items: Array<{ view: AppView; label: string; icon: ReactNode }> = [
    { view: "dashboard", label: "Dashboard", icon: <LayoutDashboard size={18} /> },
    { view: "analyze", label: "Analyze Job", icon: <FileSearch size={18} /> },
    { view: "applications", label: "Applications", icon: <BriefcaseBusiness size={18} /> },
    { view: "prep", label: "Prep Plan", icon: <CalendarCheck size={18} /> },
    { view: "leetcode", label: "Coding Practice", icon: <Code2 size={18} /> },
    { view: "resume", label: "Resume", icon: <FileText size={18} /> },
    { view: "assistant", label: "Assistant", icon: <Bot size={18} /> },
    { view: "profile", label: "Profile", icon: <FileText size={18} /> },
    { view: "settings", label: "Settings", icon: <Settings size={18} /> }
  ];

  return (
    <aside className="border-b border-slate-200 bg-white px-4 py-4 text-slate-950 lg:sticky lg:top-0 lg:min-h-screen lg:border-b-0 lg:border-r">
      <div className="mb-5 rounded-lg border border-slate-200 bg-slate-950 p-4 text-white">
        <p className="text-xs font-semibold uppercase text-slate-400">CareerPilot</p>
        <p className="mt-2 text-lg font-semibold">Career intelligence workbench</p>
        <p className="mt-2 text-xs leading-5 text-slate-300">Local-first analysis, tracking, prep, and resume workflows.</p>
      </div>
      <nav className="grid grid-cols-2 gap-1 sm:grid-cols-4 lg:grid-cols-1" aria-label="Workspace navigation">
        {items.map((item) => (
          <button
            className={`flex min-h-10 items-center gap-2 rounded-md border px-3 text-left text-sm font-semibold transition ${
              activeView === item.view ? "border-slate-300 bg-slate-100 text-slate-950" : "border-transparent text-slate-600 hover:bg-slate-50 hover:text-slate-950"
            }`}
            key={item.view}
            type="button"
            onClick={() => onChange(item.view)}
          >
            {item.icon}
            {item.label}
          </button>
        ))}
      </nav>
      <div className="mt-5 hidden rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600 lg:block">
        <p className="font-semibold text-slate-900">Demo posture</p>
        <p className="mt-1">Backend-first product surface for showing agent workflow quality, not a marketing site.</p>
      </div>
    </aside>
  );
}

function viewTitle(view: AppView): string {
  return {
    dashboard: "Dashboard",
    analyze: "Analyze Job",
    applications: "Applications",
    prep: "Prep Plan",
    leetcode: "Coding Practice",
    resume: "Resume",
    assistant: "Assistant",
    profile: "Personal Profile",
    settings: "Settings"
  }[view];
}

function viewSubtitle(view: AppView): string {
  return {
    dashboard: "Command center for applications, analysis, and preparation.",
    analyze: "Fetch or paste a role, then review fit, evidence, and next actions.",
    applications: "Track saved roles, statuses, analysis versions, and job-specific chat.",
    prep: "Generate and maintain daily preparation plans.",
    leetcode: "Track coding practice questions, tags, notes, and review status.",
    resume: "Draft role-targeted resume PDFs from profile memory and saved jobs.",
    assistant: "Ask across profile memory, saved jobs, and career strategy.",
    profile: "Inspect and update the local memory CareerPilot uses.",
    settings: "Configure local workflow and model behavior."
  }[view];
}

function DashboardView({ jobs, onNavigate }: { jobs: JobRecord[]; onNavigate: (view: AppView) => void }) {
  const appliedCount = jobs.filter((job) => job.status === "applied").length;
  const activeCount = jobs.filter((job) => !["rejected", "offer"].includes(job.status)).length;
  const topTech = jobs.flatMap((job) => buildTrackerSummary(job).techStack).slice(0, 8);
  const recentJobs = [...jobs].slice(0, 5);
  const highPriorityCount = jobs.filter((job) => job.priority === "high").length;
  const inProgressCount = jobs.filter((job) => ["saved", "interested", "applied", "interviewing"].includes(job.status)).length;

  return (
    <div className="grid gap-5">
      <PageHeader
        eyebrow="Command Center"
        title="Manage the job search like an operating workflow"
        subtitle="Review your application pipeline, surface repeated skill signals, and jump into the next analysis or preparation action."
        actions={
          <>
            <button className="primary-button" type="button" onClick={() => onNavigate("analyze")}>
              <FileSearch size={18} />
              Analyze role
            </button>
            <button className="secondary-button" type="button" onClick={() => onNavigate("applications")}>
              <BriefcaseBusiness size={18} />
              Applications
            </button>
          </>
        }
      />

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Saved roles" value={jobs.length} detail="Tracked locally" />
        <MetricCard label="Active pipeline" value={activeCount} detail={`${inProgressCount} need follow-up`} />
        <MetricCard label="Applied" value={appliedCount} detail="Submitted applications" />
        <MetricCard label="High priority" value={highPriorityCount} detail="Strong fit signals" />
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
        <Panel>
          <SectionTitle icon={<BriefcaseBusiness size={18} />} title="Recent Application Activity" subtitle="Current roles that are ready for review or follow-up." />
          <div className="mt-4 divide-y divide-slate-200">
            {recentJobs.length ? (
              recentJobs.map((job) => {
                const summary = buildTrackerSummary(job);
                return (
                  <button
                    className="grid w-full gap-2 py-3 text-left first:pt-0 last:pb-0 md:grid-cols-[minmax(0,1fr)_auto]"
                    key={job.id}
                    type="button"
                    onClick={() => onNavigate("applications")}
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-slate-950">{job.title || "Untitled job"}</p>
                      <p className="mt-1 text-xs text-slate-500">{job.company || "Unknown company"}{job.location ? ` · ${job.location}` : ""}</p>
                      <p className="mt-2 line-clamp-2 text-sm leading-5 text-slate-600">{summary.business}</p>
                    </div>
                    <div className="flex items-center gap-2 md:justify-end">
                      <Badge>{titleCase(job.status)}</Badge>
                      <RecommendationBadge fit={{ score: job.fit_score, priority: job.priority } as JobFit} compact />
                    </div>
                  </button>
                );
              })
            ) : (
              <EmptyState text="No saved roles yet. Analyze a target job to start building the pipeline." />
            )}
          </div>
        </Panel>

        <Panel>
          <SectionTitle icon={<LayoutDashboard size={18} />} title="Recommended Next Actions" subtitle="Small set of actions that keep the workflow moving." />
          <div className="mt-4 grid gap-3">
            <DashboardCard title="Analyze a target role" body="Use the analysis workspace before saving roles so the tracker stays curated." />
            <DashboardCard title="Review active applications" body={`${activeCount} saved jobs are still active in your tracker.`} />
            <DashboardCard title="Prepare from repeated gaps" body={topTech.length ? `Recent tech signals: ${Array.from(new Set(topTech)).slice(0, 5).join(", ")}.` : "Analyze a few roles to surface repeated skill gaps."} />
          </div>
        </Panel>
      </div>
    </div>
  );
}

function DashboardCard({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
      <p className="mt-1 text-sm leading-5 text-slate-600">{body}</p>
    </div>
  );
}

function PlaceholderView({ icon, title, body }: { icon: ReactNode; title: string; body: string }) {
  return (
    <Panel className="max-w-3xl">
      <SectionTitle icon={icon} title={title} subtitle="Planned workspace area." />
      <p className="mt-4 text-sm leading-6 text-slate-700">{body}</p>
    </Panel>
  );
}

function PrepPlanView({ jobs, seed }: { jobs: JobRecord[]; seed: PrepSeed | null }) {
  const queryClient = useQueryClient();
  const [timelineDays, setTimelineDays] = useState(14);
  const [hoursPerDay, setHoursPerDay] = useState(2);
  const [focus, setFocus] = useState("Kubernetes, system design, LeetCode");
  const [jobId, setJobId] = useState<number | "">("");
  const [useLlm, setUseLlm] = useState(true);
  const [importText, setImportText] = useState("");
  const [importTitle, setImportTitle] = useState("Imported prep plan");
  const plansQuery = useQuery({ queryKey: ["prep-plans"], queryFn: listPrepPlans });
  const generateMutation = useMutation({
    mutationFn: () => generatePrepPlan({ timeline_days: timelineDays, hours_per_day: hoursPerDay, focus, job_id: jobId || null, use_llm: useLlm }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prep-plans"] })
  });
  const importMutation = useMutation({
    mutationFn: () => importPrepPlan({ title: importTitle, content: importText }),
    onSuccess: async () => {
      setImportText("");
      await queryClient.invalidateQueries({ queryKey: ["prep-plans"] });
    }
  });
  const updateMutation = useMutation({
    mutationFn: ({ planId, day, taskIndex, completed }: { planId: number; day: number; taskIndex: number; completed: boolean }) =>
      updatePrepTask(planId, day, taskIndex, completed),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prep-plans"] })
  });

  useEffect(() => {
    if (!seed) {
      return;
    }
    setFocus(seed.focus);
    setJobId(seed.jobId ?? "");
  }, [seed]);

  return (
    <div className="grid min-w-0 gap-4 2xl:grid-cols-[420px_minmax(0,1fr)]">
      <Panel className="min-w-0 2xl:sticky 2xl:top-28 2xl:max-h-[calc(100vh-140px)] 2xl:overflow-y-auto">
        <SectionTitle icon={<CalendarCheck size={20} />} title="Preparation Planner" subtitle="Generate or import a daily checklist for learning, LeetCode, and interview prep." />
        <div className="mt-4 grid gap-3">
          <label className="label" htmlFor="prep-days">Timeline days</label>
          <input id="prep-days" className="input" type="number" min={1} max={90} value={timelineDays} onChange={(event) => setTimelineDays(Number(event.target.value))} />
          <label className="label" htmlFor="prep-hours">Hours per day</label>
          <input id="prep-hours" className="input" type="number" min={0.5} max={12} step={0.5} value={hoursPerDay} onChange={(event) => setHoursPerDay(Number(event.target.value))} />
          <label className="label" htmlFor="prep-job">Optional target job</label>
          <select id="prep-job" className="select" value={jobId} onChange={(event) => setJobId(event.target.value ? Number(event.target.value) : "")}>
            <option value="">General prep</option>
            {jobs.map((job) => (
              <option key={job.id} value={job.id}>{job.title || "Untitled job"} · {job.company || "Unknown"}</option>
            ))}
          </select>
          <label className="label" htmlFor="prep-focus">Focus areas</label>
          <textarea id="prep-focus" className="min-h-24 w-full rounded-md border border-slate-300 p-3 text-sm" value={focus} onChange={(event) => setFocus(event.target.value)} />
          <label className="flex items-start gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700">
            <input className="mt-0.5 h-4 w-4 accent-teal-700" type="checkbox" checked={useLlm} onChange={(event) => setUseLlm(event.target.checked)} />
            <span>
              Use LLM planner
              <span className="block text-xs font-normal text-muted">Falls back locally if the model is unavailable.</span>
            </span>
          </label>
          <button className="primary-button" type="button" disabled={generateMutation.isPending} onClick={() => generateMutation.mutate()}>
            {generateMutation.isPending ? <Loader2 className="animate-spin" size={18} /> : <CalendarCheck size={18} />}
            Generate prep plan
          </button>
        </div>

        <div className="mt-6 border-t border-slate-200 pt-4">
          <h3 className="text-sm font-semibold text-slate-950">Import Plan Text</h3>
          <input className="input mt-3" value={importTitle} onChange={(event) => setImportTitle(event.target.value)} />
          <textarea className="mt-3 min-h-36 w-full rounded-md border border-slate-300 p-3 text-sm" value={importText} onChange={(event) => setImportText(event.target.value)} placeholder="Paste your plan. Lines become checklist items; Day headings split days." />
          <button className="secondary-button mt-3" type="button" disabled={!importText.trim() || importMutation.isPending} onClick={() => importMutation.mutate()}>
            Import as checklist
          </button>
        </div>
        {(generateMutation.error || importMutation.error || plansQuery.error) ? <Feedback notice={null} error={formatUnknownError(generateMutation.error || importMutation.error || plansQuery.error)} /> : null}
      </Panel>

      <Panel className="min-w-0">
        <SectionTitle icon={<CheckCircle2 size={20} />} title="Daily Checklist" subtitle="Track preparation progress locally." />
        <div className="mt-4 grid max-h-[calc(100vh-160px)] gap-4 overflow-y-auto pr-1">
          {plansQuery.isLoading ? <EmptyState text="Loading prep plans..." /> : null}
          {!plansQuery.isLoading && (plansQuery.data ?? []).length === 0 ? <EmptyState text="No prep plans yet." /> : null}
          {(plansQuery.data ?? []).map((plan) => (
            <PrepPlanCard key={plan.id} plan={plan} onToggle={(day, taskIndex, completed) => updateMutation.mutate({ planId: plan.id, day, taskIndex, completed })} />
          ))}
        </div>
      </Panel>
    </div>
  );
}

function PrepPlanCard({ plan, onToggle }: { plan: PrepPlan; onToggle: (day: number, taskIndex: number, completed: boolean) => void }) {
  return (
    <article className="min-w-0 rounded-lg border border-slate-200 bg-white p-3">
      <h3 className="text-base font-semibold text-slate-950">{plan.title}</h3>
      <p className="mt-1 text-xs text-muted">{plan.timeline_days} days · {plan.hours_per_day}h/day · {titleCase(plan.source)}</p>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        {plan.days.map((day) => (
          <section className="min-w-0 rounded-md border border-slate-200 bg-slate-50 p-3" key={day.day}>
            <h4 className="text-sm font-semibold text-slate-950">{day.title}</h4>
            <div className="mt-2 grid gap-2">
              {day.tasks.map((task, index) => (
                <label className="flex items-start gap-2 text-sm leading-5" key={`${day.day}-${index}`}>
                  <input className="mt-1 h-4 w-4 accent-teal-700" type="checkbox" checked={task.completed} onChange={(event) => onToggle(day.day, index, event.target.checked)} />
                  <span className={`min-w-0 break-words ${task.completed ? "text-muted line-through" : "text-slate-800"}`}>
                    {task.title}
                    <span className="ml-2 text-xs font-semibold text-muted">{task.category} · {task.minutes}m</span>
                  </span>
                </label>
              ))}
            </div>
          </section>
        ))}
      </div>
    </article>
  );
}

function LeetCodeDashboard() {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [category, setCategory] = useState("linked list");
  const [tags, setTags] = useState("");
  const [note, setNote] = useState("");
  const [status, setStatus] = useState<LeetCodeStatus>("todo");
  const [formError, setFormError] = useState<string | null>(null);
  const problemsQuery = useQuery({ queryKey: ["leetcode-problems"], queryFn: listLeetCodeProblems });
  const problems = problemsQuery.data ?? [];
  const createMutation = useMutation({
    mutationFn: () => createLeetCodeProblem(buildLeetCodeRequest({ title, url, category, tags, note, status })),
    onSuccess: async () => {
      setFormError(null);
      setTitle("");
      setUrl("");
      setCategory("linked list");
      setTags("");
      setNote("");
      setStatus("todo");
      await queryClient.invalidateQueries({ queryKey: ["leetcode-problems"] });
    }
  });
  const updateMutation = useMutation({
    mutationFn: ({ problem, nextStatus }: { problem: LeetCodeProblem; nextStatus: LeetCodeStatus }) =>
      updateLeetCodeProblem(problem.id, {
        title: problem.title,
        url: problem.url,
        category: problem.category,
        tags: problem.tags,
        note: problem.note,
        status: nextStatus
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["leetcode-problems"] })
  });
  const deleteMutation = useMutation({
    mutationFn: (problemId: number) => deleteLeetCodeProblem(problemId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["leetcode-problems"] })
  });
  const solvedCount = problems.filter((problem) => problem.status === "solved").length;
  const reviewCount = problems.filter((problem) => problem.status === "review").length;
  const activeCount = problems.filter((problem) => problem.status === "todo" || problem.status === "in_progress").length;
  const topCategories = Array.from(new Set(problems.map((problem) => problem.category).filter(Boolean))).slice(0, 6);
  const topTags = Array.from(new Set(problems.flatMap((problem) => problem.tags))).slice(0, 10);

  function submitProblem() {
    if (!title.trim() || !url.trim() || !category.trim()) {
      setFormError("Title, link, and category are required.");
      return;
    }
    const normalizedUrl = normalizePracticeUrl(url);
    if (!normalizedUrl) {
      setFormError("Enter a valid practice problem link, for example https://leetcode.com/problems/two-sum/.");
      return;
    }
    setUrl(normalizedUrl);
    setFormError(null);
    createMutation.mutate();
  }

  return (
    <div className="grid gap-5">
      <PageHeader
        eyebrow="Coding Practice"
        title="Coding Practice Dashboard"
        subtitle="Track interview practice questions from LeetCode, HackerRank, NeetCode, company prep pages, or any useful source."
      />

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Tracked" value={problems.length} detail="Saved questions" />
        <MetricCard label="Active" value={activeCount} detail="Todo or in progress" />
        <MetricCard label="Solved" value={solvedCount} detail="Completed once" />
        <MetricCard label="Review" value={reviewCount} detail="Needs revisit" />
      </div>

      <div className="grid gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
        <Panel className="xl:sticky xl:top-28 xl:max-h-[calc(100vh-140px)] xl:overflow-y-auto">
          <SectionTitle icon={<Code2 size={20} />} title="Add Practice Question" subtitle="Capture enough context to review the pattern later." />
          <div className="mt-4 grid gap-3">
            <label className="label" htmlFor="leetcode-title">Question title</label>
            <input id="leetcode-title" className="input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Two Sum" />
            <label className="label" htmlFor="leetcode-url">Question link</label>
            <input id="leetcode-url" className="input" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://leetcode.com/problems/two-sum/" />
            <label className="label" htmlFor="leetcode-category">Primary category</label>
            <input id="leetcode-category" className="input" value={category} onChange={(event) => setCategory(event.target.value)} placeholder="two pointer, linked list, graph..." />
            <label className="label" htmlFor="leetcode-tags">Tags</label>
            <input id="leetcode-tags" className="input" value={tags} onChange={(event) => setTags(event.target.value)} placeholder="hash map, array, easy" />
            <label className="label" htmlFor="leetcode-status">Status</label>
            <select id="leetcode-status" className="select" value={status} onChange={(event) => setStatus(event.target.value as LeetCodeStatus)}>
              {leetcodeStatuses.map((item) => (
                <option key={item} value={item}>{formatLeetCodeStatus(item)}</option>
              ))}
            </select>
            <label className="label" htmlFor="leetcode-note">Personal note</label>
            <textarea
              id="leetcode-note"
              className="min-h-28 w-full resize-y rounded-md border border-slate-300 bg-white p-3 text-sm leading-5 text-slate-950 outline-none transition focus:border-slate-900 focus:ring-4 focus:ring-slate-900/10"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Key trick, mistake, recurrence, edge case, or revisit note..."
            />
            {formError || createMutation.error ? <Feedback notice={null} error={formError ?? formatUnknownError(createMutation.error)} /> : null}
            <button className="primary-button" type="button" disabled={!title.trim() || !url.trim() || !category.trim() || createMutation.isPending} onClick={submitProblem}>
              {createMutation.isPending ? <Loader2 className="animate-spin" size={18} /> : <Code2 size={18} />}
              Add question
            </button>
          </div>
        </Panel>

        <div className="grid gap-5">
          <Panel>
            <SectionTitle icon={<LayoutDashboard size={20} />} title="Practice Signals" subtitle="Quick view of categories and tags you are actively training." />
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <SignalGroup title="Categories" values={topCategories} empty="No categories yet." />
              <SignalGroup title="Tags" values={topTags} empty="No tags yet." />
            </div>
          </Panel>

          <Panel>
            <SectionTitle icon={<CheckCircle2 size={20} />} title="Question Tracker" subtitle="Use status as a lightweight spaced-review queue." />
            <div className="mt-4 grid gap-3">
              {problemsQuery.isLoading ? <EmptyState text="Loading practice questions..." /> : null}
              {!problemsQuery.isLoading && problems.length === 0 ? <EmptyState text="No coding practice questions yet." /> : null}
              {problems.map((problem) => (
                <LeetCodeProblemCard
                  key={problem.id}
                  problem={problem}
                  pending={updateMutation.isPending || deleteMutation.isPending}
                  onDelete={() => deleteMutation.mutate(problem.id)}
                  onStatusChange={(nextStatus) => updateMutation.mutate({ problem, nextStatus })}
                />
              ))}
              {(problemsQuery.error || updateMutation.error || deleteMutation.error) ? (
                <Feedback notice={null} error={formatUnknownError(problemsQuery.error || updateMutation.error || deleteMutation.error)} />
              ) : null}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function SignalGroup({ title, values, empty }: { title: string; values: string[]; empty: string }) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {values.length ? values.map((value) => <DataPill key={value}>{value}</DataPill>) : <span className="text-sm text-slate-500">{empty}</span>}
      </div>
    </div>
  );
}

function LeetCodeProblemCard({
  problem,
  pending,
  onDelete,
  onStatusChange
}: {
  problem: LeetCodeProblem;
  pending: boolean;
  onDelete: () => void;
  onStatusChange: (status: LeetCodeStatus) => void;
}) {
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0">
          <a className="text-base font-semibold text-slate-950 underline-offset-4 hover:underline" href={problem.url} target="_blank" rel="noreferrer">
            {problem.title}
          </a>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge>{formatLeetCodeStatus(problem.status)}</Badge>
            <DataPill>{problem.category}</DataPill>
            {problem.tags.map((tag) => <DataPill key={tag}>{tag}</DataPill>)}
          </div>
        </div>
        <div className="flex flex-wrap items-start gap-2 lg:justify-end">
          <select className="select" value={problem.status} disabled={pending} onChange={(event) => onStatusChange(event.target.value as LeetCodeStatus)}>
            {leetcodeStatuses.map((item) => (
              <option key={item} value={item}>{formatLeetCodeStatus(item)}</option>
            ))}
          </select>
          <button className="danger-button" type="button" disabled={pending} onClick={onDelete}>
            <Trash2 size={16} />
            Delete
          </button>
        </div>
      </div>
      {problem.note ? <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">{problem.note}</p> : null}
    </article>
  );
}

function buildLeetCodeRequest(values: {
  title: string;
  url: string;
  category: string;
  tags: string;
  note: string;
  status: LeetCodeStatus;
}): LeetCodeProblemRequest {
  return {
    title: values.title.trim(),
    url: normalizePracticeUrl(values.url) ?? values.url.trim(),
    category: values.category.trim(),
    tags: values.tags.split(",").map((tag) => tag.trim()).filter(Boolean),
    note: values.note.trim() || null,
    status: values.status
  };
}

function normalizePracticeUrl(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const candidate = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  try {
    const parsed = new URL(candidate);
    return parsed.toString();
  } catch {
    return null;
  }
}

function formatLeetCodeStatus(status: LeetCodeStatus): string {
  return status === "in_progress" ? "In progress" : titleCase(status);
}

function ResumeView({ jobs, seed }: { jobs: JobRecord[]; seed: ResumeSeed | null }) {
  const [roleTitle, setRoleTitle] = useState("Senior Backend Engineer");
  const [company, setCompany] = useState("");
  const [jobId, setJobId] = useState<number | "">("");
  const [notes, setNotes] = useState("");
  const [useLlm, setUseLlm] = useState(true);
  const resumeMutation = useMutation({
    mutationFn: () => generateResumePdf({ role_title: roleTitle, company: company || null, job_id: jobId || null, notes, use_llm: useLlm }),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `careerpilot-resume-${roleTitle.toLowerCase().replace(/\s+/g, "-")}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    }
  });

  useEffect(() => {
    if (!seed) {
      return;
    }
    setRoleTitle(seed.roleTitle);
    setCompany(seed.company ?? "");
    setJobId(seed.jobId ?? "");
    setNotes(seed.notes);
  }, [seed]);

  return (
    <Panel className="max-w-4xl">
      <SectionTitle icon={<FileText size={20} />} title="Resume Generator" subtitle="Generate a role-targeted PDF draft from local profile memory and optional saved job context." />
      <div className="mt-4 grid gap-3">
        <label className="label" htmlFor="resume-role">Target role</label>
        <input id="resume-role" className="input" value={roleTitle} onChange={(event) => setRoleTitle(event.target.value)} />
        <label className="label" htmlFor="resume-company">Company</label>
        <input id="resume-company" className="input" value={company} onChange={(event) => setCompany(event.target.value)} />
        <label className="label" htmlFor="resume-job">Optional saved job</label>
        <select id="resume-job" className="select" value={jobId} onChange={(event) => setJobId(event.target.value ? Number(event.target.value) : "")}>
          <option value="">Use profile only</option>
          {jobs.map((job) => (
            <option key={job.id} value={job.id}>{job.title || "Untitled job"} · {job.company || "Unknown"}</option>
          ))}
        </select>
        <label className="label" htmlFor="resume-notes">Extra positioning notes</label>
        <textarea id="resume-notes" className="min-h-36 w-full rounded-md border border-slate-300 p-3 text-sm" value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Paste role-specific notes, keywords, or resume emphasis you want included..." />
        <label className="flex items-start gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700">
          <input className="mt-0.5 h-4 w-4 accent-teal-700" type="checkbox" checked={useLlm} onChange={(event) => setUseLlm(event.target.checked)} />
          <span>
            Use LLM resume writer
            <span className="block text-xs font-normal text-muted">Falls back to a local draft if the model is unavailable.</span>
          </span>
        </label>
        {resumeMutation.error ? <Feedback notice={null} error={formatUnknownError(resumeMutation.error)} /> : null}
        <button className="primary-button justify-self-start" type="button" disabled={!roleTitle.trim() || resumeMutation.isPending} onClick={() => resumeMutation.mutate()}>
          {resumeMutation.isPending ? <Loader2 className="animate-spin" size={18} /> : <Download size={18} />}
          Generate PDF
        </button>
      </div>
    </Panel>
  );
}

function ProfileView() {
  const queryClient = useQueryClient();
  const [resumeText, setResumeText] = useState("");
  const [resumeFilename, setResumeFilename] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<ResumeExtractResponse | null>(null);
  const [proposalMessage, setProposalMessage] = useState("");
  const [proposalChat, setProposalChat] = useState<Array<{ role: "user" | "assistant"; content: string }>>([]);
  const profileQuery = useQuery({
    queryKey: ["profile"],
    queryFn: getProfile
  });
  const extractMutation = useMutation({
    mutationFn: () => extractResumeProfile({ filename: resumeFilename, content: resumeText }),
    onSuccess: (result) => {
      setExtraction(result);
      setProposalChat([]);
    }
  });
  const refineMutation = useMutation({
    mutationFn: (content: string) =>
      refineProfileProposal({
        proposal_id: extraction?.proposal_id ?? null,
        proposed_updates: extraction?.proposed_updates ?? {},
        message: content,
        use_llm: true
      }),
    onSuccess: (result: ProfileProposalRefineResponse, content) => {
      setExtraction((current) =>
        current
          ? {
              ...current,
              proposed_updates: result.proposed_updates,
              summary: `Proposal refined with ${result.responder_used}${result.responder_warning ? " fallback" : ""}.`
            }
          : current
      );
      setProposalChat((current) => [
        ...current,
        { role: "user", content },
        { role: "assistant", content: result.responder_warning ? `${result.answer}\n\nNote: ${result.responder_warning}` : result.answer }
      ]);
      setProposalMessage("");
    }
  });
  const applyMutation = useMutation({
    mutationFn: () => applyProfileUpdates({ proposal_id: extraction?.proposal_id ?? null, proposed_updates: extraction?.proposed_updates ?? {}, source: "resume_portal" }),
    onSuccess: async (result) => {
      setExtraction({
        filename: resumeFilename,
        proposal_id: extraction?.proposal_id ?? null,
        proposed_updates: {},
        summary: result.summary
      });
      setProposalChat([]);
      await queryClient.invalidateQueries({ queryKey: ["profile"] });
    }
  });

  async function loadResumeFile(file: File) {
    setResumeFilename(file.name);
    setExtraction(null);
    if (file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")) {
      setResumeText("");
      setExtraction({
        filename: file.name,
        proposed_updates: {},
        summary: "PDF upload is recognized, but this first portal reads Markdown or plain-text resumes. Convert the PDF text or paste it below for extraction."
      });
      return;
    }
    setResumeText(await file.text());
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(420px,0.85fr)_minmax(520px,1.15fr)]">
      <Panel>
        <SectionTitle icon={<FileText size={20} />} title="Personal Profile" subtitle="What CareerPilot currently knows about your background and preferences." />
        {profileQuery.isLoading ? <EmptyState text="Loading profile memory..." /> : null}
        {profileQuery.error ? (
          <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">
            {formatUnknownError(profileQuery.error)}
          </div>
        ) : null}
        {profileQuery.data ? (
          <div className="mt-4">
            <DataPill className="mb-3">
              Source: {profileQuery.data.source === "local" ? "Private local profile" : "Example template"}
            </DataPill>
            <ProfileSections profile={profileQuery.data.profile} />
          </div>
        ) : null}
      </Panel>

      <Panel>
        <SectionTitle icon={<FileText size={20} />} title="Resume Portal" subtitle="Upload or paste resume text to propose profile-memory updates." />
        <div className="mt-4 space-y-3">
          <input
            className="block w-full rounded-md border border-slate-300 bg-white p-2 text-sm"
            type="file"
            accept=".md,.txt,.pdf"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                void loadResumeFile(file);
              }
            }}
          />
          <textarea
            className="min-h-64 w-full resize-y rounded-md border border-slate-300 bg-white p-3 text-sm leading-5 text-slate-950 outline-none transition focus:border-slate-900 focus:ring-4 focus:ring-slate-900/10"
            value={resumeText}
            onChange={(event) => {
              setResumeText(event.target.value);
              setExtraction(null);
            }}
            placeholder="Paste Markdown or plain-text resume content here..."
          />
          <button className="primary-button" type="button" disabled={!resumeText.trim() || extractMutation.isPending} onClick={() => extractMutation.mutate()}>
            {extractMutation.isPending ? <Loader2 className="animate-spin" size={18} /> : <FileSearch size={18} />}
            Extract proposed updates
          </button>
        </div>

        {extractMutation.error ? (
          <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">
            {formatUnknownError(extractMutation.error)}
          </div>
        ) : null}
        {extraction ? (
          <ResumeExtractionResult
            applyError={applyMutation.error}
            chatError={refineMutation.error}
            chatMessage={proposalMessage}
            chatMessages={proposalChat}
            extraction={extraction}
            isApplying={applyMutation.isPending}
            isChatting={refineMutation.isPending}
            onApply={() => applyMutation.mutate()}
            onChatMessageChange={setProposalMessage}
            onSubmitChat={() => {
              const trimmed = proposalMessage.trim();
              if (trimmed) {
                refineMutation.mutate(trimmed);
              }
            }}
          />
        ) : null}
      </Panel>
    </div>
  );
}

function ProfileSections({ profile }: { profile: Record<string, unknown> }) {
  const entries = Object.entries(profile);
  if (!entries.length) {
    return <EmptyState text="No profile facts found yet." />;
  }
  return (
    <div className="grid gap-3">
      {entries.map(([key, value]) => (
        <section className="rounded-lg border border-slate-200 bg-white p-3" key={key}>
          <h3 className="text-sm font-semibold text-slate-950">{titleCase(key)}</h3>
          <ProfileValue value={value} />
        </section>
      ))}
    </div>
  );
}

function ProfileValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    if (value.length > 0 && value.every((item) => item && typeof item === "object" && !Array.isArray(item))) {
      return (
        <div className="mt-3 grid gap-3">
          {value.map((item, index) => (
            <ProfileObjectCard key={index} value={item as Record<string, unknown>} />
          ))}
        </div>
      );
    }
    return (
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-5 text-slate-700">
        {value.map((item, index) => (
          <li key={index}>{formatProfilePrimitive(item)}</li>
        ))}
      </ul>
    );
  }
  if (value && typeof value === "object") {
    return (
      <div className="mt-2 grid gap-2">
        {Object.entries(value as Record<string, unknown>).map(([key, nested]) => (
          <div key={key}>
            <p className="text-xs font-semibold uppercase text-slate-500">{titleCase(key)}</p>
            <ProfileValue value={nested} />
          </div>
        ))}
      </div>
    );
  }
  return <p className="mt-2 text-sm leading-5 text-slate-700">{formatProfilePrimitive(value)}</p>;
}

function ProfileObjectCard({ value }: { value: Record<string, unknown> }) {
  const title = profileObjectTitle(value);
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      {title ? <p className="text-sm font-semibold text-slate-950">{title}</p> : null}
      <div className={title ? "mt-2 grid gap-2" : "grid gap-2"}>
        {Object.entries(value)
          .filter(([key]) => !["name", "title", "company", "school", "institution"].includes(key))
          .map(([key, nested]) => (
            <div key={key}>
              <p className="text-xs font-semibold uppercase text-slate-500">{titleCase(key)}</p>
              <ProfileValue value={nested} />
            </div>
          ))}
      </div>
    </div>
  );
}

function profileObjectTitle(value: Record<string, unknown>): string | null {
  for (const key of ["name", "title", "company", "school", "institution"]) {
    const candidate = value[key];
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate;
    }
  }
  return null;
}

function formatProfilePrimitive(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "Not set";
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "number") {
    return String(value);
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value);
}

function ResumeExtractionResult({
  applyError,
  chatError,
  chatMessage,
  chatMessages,
  extraction,
  isApplying,
  isChatting,
  onApply,
  onChatMessageChange,
  onSubmitChat
}: {
  applyError: unknown;
  chatError: unknown;
  chatMessage: string;
  chatMessages: Array<{ role: "user" | "assistant"; content: string }>;
  extraction: ResumeExtractResponse;
  isApplying: boolean;
  isChatting: boolean;
  onApply: () => void;
  onChatMessageChange: (value: string) => void;
  onSubmitChat: () => void;
}) {
  const hasUpdates = Object.values(extraction.proposed_updates).some((values) => values.length > 0);
  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <h3 className="text-sm font-semibold text-slate-950">Proposed Profile Updates</h3>
      <p className="mt-1 text-sm leading-5 text-muted">{extraction.summary}</p>
      <div className="mt-3 grid gap-3">
        {Object.entries(extraction.proposed_updates).map(([key, values]) => (
          <section className="rounded-md border border-slate-200 bg-white p-3" key={key}>
            <h4 className="text-sm font-semibold text-slate-950">{titleCase(key)}</h4>
            {values.length ? (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-5 text-slate-700">
                {values.map((value) => (
                  <li key={value}>{value}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-muted">No signals detected.</p>
            )}
          </section>
        ))}
      </div>
      {hasUpdates ? (
        <div className="mt-4 rounded-md border border-slate-200 bg-white p-3">
          <h4 className="text-sm font-semibold text-slate-950">Proposal Assistant</h4>
          <p className="mt-1 text-xs leading-5 text-muted">
            Ask for changes before saving, for example: `remove Kubernetes` or `add Java to technical_strengths`.
          </p>
          <div className="mt-3 max-h-56 space-y-2 overflow-y-auto">
            {chatMessages.length === 0 ? <EmptyState text="No proposal discussion yet." /> : null}
            {chatMessages.map((message, index) => (
              <div className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`} key={index}>
                <div
                  className={`max-w-[92%] rounded-md px-3 py-2 text-sm leading-5 ${
                    message.role === "user" ? "border border-slate-300 bg-slate-100 text-slate-900" : "border border-slate-200 bg-white text-slate-800"
                  }`}
                >
                  <MarkdownMessage content={message.content} />
                </div>
              </div>
            ))}
            {isChatting ? <StreamingAssistantBubble answer="" statuses={["Refining proposal"]} /> : null}
          </div>
          {chatError ? (
            <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">
              {formatUnknownError(chatError)}
            </div>
          ) : null}
          <div className="mt-3 flex flex-col gap-2">
            <textarea
              className="min-h-20 w-full resize-y rounded-md border border-slate-300 bg-white p-3 text-sm leading-5 text-slate-950 outline-none transition focus:border-slate-900 focus:ring-4 focus:ring-slate-900/10"
              value={chatMessage}
              onChange={(event) => onChatMessageChange(event.target.value)}
              placeholder="Ask the assistant to add, remove, clarify, or reclassify proposed profile facts..."
            />
            <button className="secondary-button self-end" type="button" disabled={isChatting || !chatMessage.trim()} onClick={onSubmitChat}>
              {isChatting ? <Loader2 className="animate-spin" size={18} /> : <Send size={18} />}
              Refine proposal
            </button>
          </div>
        </div>
      ) : null}
      {applyError ? (
        <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">
          {formatUnknownError(applyError)}
        </div>
      ) : null}
      <div className="mt-4 flex justify-end">
        <button className="primary-button" type="button" disabled={!hasUpdates || isApplying} onClick={onApply}>
          {isApplying ? <Loader2 className="animate-spin" size={18} /> : <CheckCircle2 size={18} />}
          Save to profile memory
        </button>
      </div>
    </div>
  );
}

function GlobalAssistantView() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");
  const [useWebSearch, setUseWebSearch] = useState(false);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [draftMessages, setDraftMessages] = useState<GlobalChatMessage[]>([]);
  const [actionTasksBySession, setActionTasksBySession] = useState<Record<number, string[]>>({});
  const sessionsQuery = useQuery({
    queryKey: ["global-chat-sessions"],
    queryFn: listGlobalChatSessions
  });
  const chatQuery = useQuery({
    queryKey: ["global-chat", activeSessionId],
    queryFn: () => listGlobalChatForSession(activeSessionId as number),
    enabled: activeSessionId !== null
  });
  const sessions = sessionsQuery.data ?? [];

  const clearHistoryMutation = useMutation({
    mutationFn: (sessionId: number) => clearGlobalChatSession(sessionId),
    onSuccess: async () => {
      setDraftMessages([]);
      await queryClient.invalidateQueries({ queryKey: ["global-chat", activeSessionId] });
    }
  });
  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: number) => deleteGlobalChatSession(sessionId),
    onSuccess: async (_result, deletedId) => {
      setActiveSessionId((current) => (current === deletedId ? null : current));
      setDraftMessages([]);
      await queryClient.invalidateQueries({ queryKey: ["global-chat-sessions"] });
    }
  });
  const chatMutation = useMutation({
    mutationFn: (content: string) =>
      sendGlobalChat({ message: content, session_id: activeSessionId, use_web_search: useWebSearch }),
    onSuccess: async (response) => {
      setMessage("");
      setActiveSessionId(response.session.id);
      setDraftMessages([]);
      if (response.actions.length > 0) {
        setActionTasksBySession((current) => {
          const existing = current[response.session.id] ?? [];
          const incoming = response.actions.map((action) => action.id);
          return {
            ...current,
            [response.session.id]: [...incoming, ...existing.filter((id) => !incoming.includes(id))]
          };
        });
      }
      await queryClient.invalidateQueries({ queryKey: ["global-chat", response.session.id] });
      await queryClient.invalidateQueries({ queryKey: ["global-chat-sessions"] });
    }
  });

  const prompts = [
    "Rank my saved jobs for AI platform transition.",
    "Build me a 2-week prep plan.",
    "What gaps show up across my saved roles?",
    "Which job should I apply to next?"
  ];

  function submitChat(content = message) {
    const trimmed = content.trim();
    if (!trimmed || chatMutation.isPending) {
      return;
    }
    setMessage("");
    setDraftMessages((current) => [
      ...current,
      {
        id: -Date.now(),
        session_id: activeSessionId,
        role: "user",
        content: trimmed,
        used_web_search: false,
        citations: []
      }
    ]);
    chatMutation.mutate(trimmed);
  }

  function startFreshChat() {
    setActiveSessionId(null);
    setDraftMessages([]);
    setMessage("");
  }

  const visibleMessages = activeSessionId === null ? draftMessages : chatQuery.data ?? [];
  const activeSession = sessions.find((session) => session.id === activeSessionId) ?? null;
  const visibleActionTaskIds = activeSessionId === null ? [] : actionTasksBySession[activeSessionId] ?? [];

  return (
    <section className="grid gap-5 xl:grid-cols-[300px_minmax(520px,1fr)]">
      <Panel className="xl:h-[calc(100vh-150px)] xl:min-h-[620px] xl:overflow-y-auto" padding="compact">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-950">Chats</h2>
          <button className="secondary-button px-2" type="button" onClick={startFreshChat}>
            <MessageCircle size={16} />
            New
          </button>
        </div>
        {sessionsQuery.isLoading ? <EmptyState text="Loading chats..." /> : null}
        {!sessionsQuery.isLoading && sessions.length === 0 ? <EmptyState text="No saved chats yet." /> : null}
        <div className="grid gap-1">
          {sessions.map((session) => (
            <ChatSessionButton
              key={session.id}
              active={session.id === activeSessionId}
              session={session}
              onSelect={() => {
                setActiveSessionId(session.id);
                setDraftMessages([]);
              }}
              onDelete={() => deleteSessionMutation.mutate(session.id)}
            />
          ))}
        </div>
      </Panel>

      <Panel className="flex xl:h-[calc(100vh-150px)] xl:min-h-[620px] xl:flex-col">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-xs font-semibold uppercase text-slate-500">Assistant Chat</p>
            <h2 className="mt-1 text-lg font-semibold text-slate-950">{activeSession?.title ?? "New chat"}</h2>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="inline-flex min-h-10 items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 text-sm font-semibold text-slate-700">
              <input
                className="h-4 w-4 accent-teal-700"
                type="checkbox"
                checked={useWebSearch}
                onChange={(event) => setUseWebSearch(event.target.checked)}
              />
              Web search
            </label>
            {activeSessionId !== null ? (
              <button className="danger-button" type="button" onClick={() => clearHistoryMutation.mutate(activeSessionId)}>
                <Trash2 size={16} />
                Clear thread
              </button>
            ) : null}
          </div>
        </div>
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
          {activeSessionId !== null && chatQuery.isLoading ? <EmptyState text="Loading conversation..." /> : null}
          {!chatQuery.isLoading && visibleMessages.length === 0 ? (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
              <SectionTitle
                icon={<Bot size={20} />}
                title="Global Assistant"
                subtitle="Ask across your profile, saved jobs, application statuses, and local chat history."
              />
              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                {sessions.length > 0 ? (
                  <div className="rounded-md border border-slate-200 bg-white p-3 text-sm leading-5 text-slate-500 sm:col-span-2">
                    Start a fresh chat with one of the prompts below, or select a saved conversation from the chat history.
                  </div>
                ) : null}
                {prompts.map((prompt) => (
                  <button className="secondary-button justify-start" key={prompt} type="button" onClick={() => submitChat(prompt)}>
                    <MessageCircle size={16} />
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {visibleMessages.map((chatMessage) => (
            <GlobalChatBubble key={chatMessage.id} message={chatMessage} />
          ))}
          {visibleActionTaskIds.map((taskId) => (
            <ChatActionTaskCard key={taskId} taskId={taskId} />
          ))}
          {chatMutation.isPending ? <StreamingAssistantBubble answer="" statuses={["Thinking through saved profile and applications"]} /> : null}
        </div>

        {chatMutation.error ? (
          <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">
            {formatUnknownError(chatMutation.error)}
          </div>
        ) : null}

        <div className="sticky bottom-0 -mx-4 mt-3 flex flex-col gap-2 border-t border-slate-200 bg-white/95 px-4 pb-1 pt-3 backdrop-blur">
          <textarea
            className="min-h-28 w-full resize-y rounded-md border border-slate-300 bg-white p-3 text-sm leading-5 text-slate-950 outline-none transition focus:border-slate-900 focus:ring-4 focus:ring-slate-900/10"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="Ask about saved jobs, prep priorities, skill gaps, or career strategy..."
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs leading-5 text-muted">
              {useWebSearch ? "Web search is on for this message." : "Web search is off; answers use local profile and saved jobs."}
            </p>
            <button className="primary-button" type="button" disabled={chatMutation.isPending || !message.trim()} onClick={() => submitChat()}>
              {chatMutation.isPending ? <Loader2 className="animate-spin" size={18} /> : <Send size={18} />}
              Send
            </button>
          </div>
        </div>
      </Panel>
    </section>
  );
}

function ChatSessionButton({
  active,
  session,
  onDelete,
  onSelect
}: {
  active: boolean;
  session: GlobalChatSession;
  onDelete: () => void;
  onSelect: () => void;
}) {
  return (
    <div className={`group grid grid-cols-[1fr_auto] items-center rounded-md border ${active ? "border-slate-900 bg-slate-950 text-white" : "border-transparent hover:border-slate-200 hover:bg-slate-50"}`}>
      <button className="min-h-10 truncate px-3 text-left text-sm font-semibold" type="button" onClick={onSelect} title={session.title}>
        {session.title}
      </button>
      <button
        className={`mr-1 flex h-8 w-8 items-center justify-center rounded text-sm transition ${
          active ? "text-slate-300 hover:bg-slate-800 hover:text-white" : "text-muted hover:bg-white hover:text-rose-700"
        }`}
        type="button"
        aria-label={`Delete ${session.title}`}
        onClick={onDelete}
      >
        <Trash2 size={15} />
      </button>
    </div>
  );
}

function GlobalChatBubble({ message }: { message: GlobalChatMessage }) {
  return <ChatBubble message={message} />;
}

function AnalyzeJobView({
  activeError,
  analysis,
  analyzePending,
  backgroundSavePending,
  backgroundTask,
  refreshContext,
  description,
  fetchPending,
  inputMode,
  isAnalyzing,
  jobUrl,
  notice,
  saveAnalysis,
  applyAnalysisUpdate,
  savePending,
  applyUpdatePending,
  showFetchedText,
  submitAnalysis,
  submitBackgroundSave,
  submitFetch,
  setDescription,
  setInputMode,
  setJobUrl,
  setShowFetchedText,
  onCreatePrepPlan,
  onGenerateResume
}: {
  activeError: string | null;
  analysis: JobAnalysisResponse | null;
  analyzePending: boolean;
  backgroundSavePending: boolean;
  backgroundTask: AgentTask | null;
  refreshContext: AnalysisRefreshContext | null;
  description: string;
  fetchPending: boolean;
  inputMode: InputMode;
  isAnalyzing: boolean;
  jobUrl: string;
  notice: string | null;
  saveAnalysis: () => void;
  applyAnalysisUpdate: () => void;
  savePending: boolean;
  applyUpdatePending: boolean;
  showFetchedText: boolean;
  submitAnalysis: () => void;
  submitBackgroundSave: () => void;
  submitFetch: () => void;
  setDescription: (value: string) => void;
  setInputMode: (value: InputMode) => void;
  setJobUrl: (value: string) => void;
  setShowFetchedText: (updater: (current: boolean) => boolean) => void;
  onCreatePrepPlan: (analysis: JobAnalysisResponse) => void;
  onGenerateResume: (analysis: JobAnalysisResponse) => void;
}) {
  return (
    <div className="grid gap-5 2xl:grid-cols-[minmax(360px,440px)_minmax(760px,1fr)]">
      <Panel className="2xl:sticky 2xl:top-28 2xl:max-h-[calc(100vh-140px)] 2xl:overflow-y-auto">
        <SectionTitle icon={<FileSearch size={20} />} title="Analyze Source" subtitle="Fetch from a job URL or paste a clean description." />

        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-2 rounded-md border border-slate-200 bg-slate-100 p-1" role="tablist" aria-label="Job input mode">
            <ModeButton active={inputMode === "link"} icon={<Link size={16} />} label="Job Link" onClick={() => setInputMode("link")} />
            <ModeButton active={inputMode === "paste"} icon={<Clipboard size={16} />} label="Paste Text" onClick={() => setInputMode("paste")} />
          </div>

          <div>
            <label className="label" htmlFor="job-url">
              {inputMode === "link" ? "Job link" : "Optional source link"}
            </label>
            <div className="mt-2 flex flex-col gap-2 sm:flex-row">
              <input
                id="job-url"
                className="input"
                type="url"
                value={jobUrl}
                onChange={(event) => setJobUrl(event.target.value)}
                placeholder="https://company.example/jobs/senior-backend-engineer"
              />
              {inputMode === "link" ? (
                <div className="flex flex-col gap-2 sm:flex-row">
                  <button className="primary-button" type="button" disabled={isAnalyzing} onClick={submitFetch}>
                    {fetchPending ? <Loader2 className="animate-spin" size={18} /> : <Link size={18} />}
                    Fetch & Analyze
                  </button>
                  <button className="secondary-button" type="button" disabled={backgroundSavePending} onClick={submitBackgroundSave}>
                    {backgroundSavePending ? <Loader2 className="animate-spin" size={18} /> : <BriefcaseBusiness size={18} />}
                    Save in background
                  </button>
                </div>
              ) : null}
            </div>
          </div>

          <Feedback notice={notice} error={activeError} />
          {refreshContext ? (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              <span className="font-bold">Refreshing saved job:</span> {refreshContext.title}
              <span className="block text-xs">Review the new analysis before updating the saved tracker record.</span>
            </div>
          ) : null}
          {backgroundTask ? (
            <BackgroundTaskStatus task={backgroundTask} />
          ) : fetchPending || backgroundSavePending ? (
            <BackgroundTaskStarting save={backgroundSavePending} />
          ) : null}

          {inputMode === "link" && description ? (
            <button className="secondary-button" type="button" onClick={() => setShowFetchedText((current) => !current)}>
              {showFetchedText ? <EyeOff size={18} /> : <Eye size={18} />}
              {showFetchedText ? "Hide fetched text" : "View fetched text"}
            </button>
          ) : null}

          {inputMode === "paste" || showFetchedText ? (
            <div>
              <label className="label" htmlFor="job-description">
                {inputMode === "link" ? "Fetched job text" : "Job description"}
              </label>
              <textarea
                id="job-description"
                className="textarea mt-2"
                readOnly={inputMode === "link"}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder={"Senior Backend Engineer, AI Platform\nCompany: Example AI\nLocation: Remote\n\nBuild Python backend APIs and distributed workflow orchestration for LLM agent systems..."}
              />
            </div>
          ) : null}

          <div className="flex justify-end">
            {inputMode === "paste" ? (
              <button className="primary-button" type="button" disabled={isAnalyzing} onClick={submitAnalysis}>
                {analyzePending ? <Loader2 className="animate-spin" size={18} /> : <Send size={18} />}
                Analyze
              </button>
            ) : null}
          </div>
        </div>
      </Panel>

      {analysis ? (
        <AnalysisResult
          analysis={analysis}
          onCreatePrepPlan={() => onCreatePrepPlan(analysis)}
          onGenerateResume={() => onGenerateResume(analysis)}
          onSave={saveAnalysis}
          onApplyUpdate={applyAnalysisUpdate}
          refreshContext={refreshContext}
          savePending={savePending}
          applyUpdatePending={applyUpdatePending}
          sourceUrl={jobUrl.trim() || null}
        />
      ) : (
        <PlaceholderView
          icon={<CheckCircle2 size={22} />}
          title="Latest Analysis"
          body="Fetch or paste a job to generate role fit, prep guidance, resume emphasis, and detected gaps."
        />
      )}
    </div>
  );
}

function SectionHeader({
  icon,
  title,
  subtitle
}: {
  icon: ReactNode;
  title: string;
  subtitle: string;
}) {
  return <SectionTitle icon={icon} title={title} subtitle={subtitle} />;
}

function ModeButton({
  active,
  icon,
  label,
  onClick
}: {
  active: boolean;
  icon: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className={`min-h-10 rounded px-3 text-sm font-semibold transition ${
        active ? "bg-white text-slate-950 shadow-sm" : "text-slate-600 hover:text-slate-900"
      }`}
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
    >
      <span className="inline-flex items-center justify-center gap-2">
        {icon}
        {label}
      </span>
    </button>
  );
}

function Feedback({ notice, error }: { notice: string | null; error: string | null }) {
  if (!notice && !error) {
    return null;
  }
  return (
    <div
      className={`flex items-start gap-2 rounded-md border px-3 py-2 text-sm font-semibold ${
        error ? "border-rose-200 bg-rose-50 text-rose-700" : "border-emerald-200 bg-emerald-50 text-emerald-700"
      }`}
    >
      {error ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}
      <span>{error ?? notice}</span>
    </div>
  );
}

function BackgroundTaskStarting({ save }: { save: boolean }) {
  return (
    <div className="rounded-lg border border-teal-200 bg-teal-50/70 p-4 text-sm shadow-sm">
      <div className="flex items-start gap-3">
        <div className="rounded-md bg-white p-2 text-teal-700 shadow-sm">
          <Loader2 className="animate-spin" size={18} />
        </div>
        <div>
          <p className="font-semibold text-slate-950">Starting workflow</p>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            CareerPilot is creating a background task for {save ? "fetch, analysis, and tracker save" : "fetch and analysis preview"}. Progress will appear here shortly.
          </p>
        </div>
      </div>
    </div>
  );
}

function BackgroundTaskStatus({ task }: { task: AgentTask }) {
  const url = typeof task.input.url === "string" ? task.input.url : "Unknown URL";
  const savedJob = task.artifacts.saved_job;
  const workflowGraph = task.artifacts.workflow_graph;
  const traceEvents = task.artifacts.workflow_run?.trace_events ?? [];
  const completedSteps = task.steps.filter((step) => step.status === "completed").length;
  const failedSteps = task.steps.filter((step) => step.status === "failed").length;
  const totalSteps = Math.max(task.steps.length, workflowGraph?.nodes.length ?? 0, 1);
  const progress = task.status === "completed" ? 100 : task.status === "failed" ? Math.round((completedSteps / totalSteps) * 100) : Math.max(8, Math.round((completedSteps / totalSteps) * 100));
  const currentStep = task.steps.find((step) => step.status === "running") ?? task.steps.find((step) => step.status === "queued") ?? task.steps[task.steps.length - 1];
  const hasNestedAnalysis = task.steps.some((step) => step.name.startsWith("analysis_"));
  const statusTone =
    task.status === "completed"
      ? "text-emerald-700"
      : task.status === "failed"
        ? "text-rose-700"
        : "text-amber-800";
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1">
          <div className={`flex items-center gap-2 font-semibold ${statusTone}`}>
            {task.status === "completed" ? <CheckCircle2 size={18} /> : task.status === "failed" ? <AlertCircle size={18} /> : <Loader2 className="animate-spin" size={18} />}
            <span>{titleCase(task.status)} analysis workflow</span>
          </div>
          <p className="mt-1 truncate text-xs text-slate-500" title={url}>
            {url}
          </p>
          {currentStep ? (
            <p className="mt-2 text-xs font-medium text-slate-700">
              Current: <span className="text-slate-950">{formatWorkflowStepName(currentStep.name)}</span>
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2 sm:justify-end">
          <Badge tone={task.status === "completed" ? "success" : task.status === "failed" ? "danger" : "warning"}>
            {completedSteps}/{totalSteps} steps
          </Badge>
          {hasNestedAnalysis ? <Badge tone="neutral">LLM stages visible</Badge> : null}
        </div>
      </div>

      <div className="mt-3">
        <div className="h-2 overflow-hidden rounded-full bg-slate-100">
          <div
            className={`h-full rounded-full transition-all ${task.status === "failed" ? "bg-rose-500" : task.status === "completed" ? "bg-emerald-500" : "bg-amber-500"}`}
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
          <span>{currentStep?.summary || "Fetching, analyzing, validating, and preparing guidance."}</span>
          {failedSteps > 0 ? <span className="font-semibold text-rose-700">{failedSteps} failed</span> : <span>{progress}%</span>}
        </div>
      </div>

      {task.steps.length > 0 ? (
        <ol className="mt-4 grid gap-2 text-xs leading-5">
          {task.steps.map((step) => (
            <li className={`grid gap-3 rounded-md border px-3 py-2 sm:grid-cols-[auto_minmax(0,1fr)] ${step.name.startsWith("analysis_") ? "border-teal-100 bg-teal-50/45" : "border-slate-200 bg-slate-50"}`} key={`${step.name}-${step.started_at ?? step.status}`}>
              <WorkflowStepStatusIcon step={step} />
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-slate-900">{formatWorkflowStepName(step.name)}</span>
                  {step.name.startsWith("analysis_") ? <span className="text-[10px] font-bold uppercase text-teal-700">analysis stage</span> : null}
                </div>
                {step.summary ? <span className="block text-slate-600">{step.summary}</span> : null}
                {step.error ? <span className="block font-semibold text-rose-700">{step.error}</span> : null}
              </div>
            </li>
          ))}
        </ol>
      ) : null}
      {workflowGraph ? <WorkflowGraphPreview graph={workflowGraph} fallbackSteps={task.steps} /> : null}
      {traceEvents.length > 0 ? (
        <details className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-2">
          <summary className="cursor-pointer text-xs font-semibold text-slate-700">Trace events</summary>
          <WorkflowTraceTimeline events={traceEvents} />
        </details>
      ) : null}
      {savedJob ? (
        <p className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700">
          Saved {savedJob.title || "Untitled job"} as {applicationTypeLabel(savedJob.application_type)}.
        </p>
      ) : null}
      {task.error ? <p className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-700">{task.error}</p> : null}
    </div>
  );
}

function WorkflowStepStatusIcon({ step }: { step: AgentTaskStep }) {
  if (step.status === "completed") {
    return <CheckCircle2 className="mt-0.5 text-emerald-600" size={18} />;
  }
  if (step.status === "failed" || step.status === "blocked") {
    return <AlertCircle className="mt-0.5 text-rose-600" size={18} />;
  }
  if (step.status === "running") {
    return <Loader2 className="mt-0.5 animate-spin text-amber-600" size={18} />;
  }
  return <Clock className="mt-0.5 text-slate-400" size={18} />;
}

function formatWorkflowStepName(name: string) {
  return name.replace(/^analysis_/, "").replace(/_/g, " ");
}

function WorkflowGraphPreview({
  graph,
  fallbackSteps = []
}: {
  graph: NonNullable<AgentTask["artifacts"]["workflow_graph"]>;
  fallbackSteps?: AgentTask["steps"];
}) {
  // Render backend-owned workflow semantics generically. The UI should not know
  // that job ingestion means fetch -> analyze -> save; it just receives nodes
  // and edges and decides how to present them.
  const stepStatusByName = new Map(fallbackSteps.map((step) => [step.name, step.status]));
  const dependencyText = graph.edges.length
    ? graph.edges.map((edge) => `${edge.source.replace(/_/g, " ")} -> ${edge.target.replace(/_/g, " ")}`).join(", ")
    : "No dependencies";
  return (
    <div className="mt-3 rounded-md border border-current/15 bg-white/55 p-2 text-xs text-slate-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-bold">{graph.workflow_id.replace(/_/g, " ")} workflow</span>
        <span className="text-[11px] font-semibold text-slate-500">v{graph.workflow_version}</span>
      </div>
      <div className="mt-2 grid gap-2 md:grid-cols-3">
        {graph.nodes.map((node) => {
          const status = stepStatusByName.get(node.id) ?? node.status;
          return (
            <div className="rounded border border-slate-200 bg-white px-2 py-1.5" key={node.id}>
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-bold text-slate-900" title={node.label}>
                  {node.label}
                </span>
                <StatusPill status={status} />
              </div>
              {node.description ? <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-600">{node.description}</p> : null}
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-[11px] leading-4 text-slate-600">{dependencyText}</p>
    </div>
  );
}

function WorkflowTraceTimeline({ events }: { events: NonNullable<AgentTask["artifacts"]["workflow_run"]>["trace_events"] }) {
  const visibleEvents = events.slice(-8);
  return (
    <div className="mt-3 text-xs">
      <div className="font-bold">Trace events</div>
      <ol className="mt-1 space-y-1">
        {visibleEvents.map((event, index) => (
          <li className="flex items-start gap-2" key={`${event.task_id}-${event.event}-${event.timestamp}-${index}`}>
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-current" />
            <span>
              <span className="font-semibold">{event.task_id.replace(/_/g, " ")}</span>
              <span className="ml-1">{event.event}</span>
              {event.detail ? <span className="block font-normal">{event.detail}</span> : null}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const className =
    status === "completed"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : status === "failed" || status === "blocked"
        ? "border-rose-200 bg-rose-50 text-rose-700"
        : status === "running"
          ? "border-amber-200 bg-amber-50 text-amber-800"
          : "border-slate-200 bg-slate-50 text-slate-600";
  return (
    <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-normal ${className}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

function ChatActionTaskCard({ taskId }: { taskId: string }) {
  const queryClient = useQueryClient();
  const taskQuery = useQuery({
    queryKey: ["chat-action-task", taskId],
    queryFn: () => getBackgroundJobIngest(taskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 1500 : false;
    }
  });
  const task = taskQuery.data;

  useEffect(() => {
    if (task?.status === "completed") {
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    }
  }, [queryClient, task?.status]);

  if (taskQuery.isLoading) {
    return (
      <div className="ml-10 rounded-md border border-amber-100 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-700">
        <Loader2 className="mr-2 inline animate-spin" size={16} />
        Loading agent task...
      </div>
    );
  }

  if (!task) {
    return null;
  }

  return (
    <div className="ml-10">
      <BackgroundTaskStatus task={task} />
    </div>
  );
}

type AnalysisReviewItem = {
  text: string;
  evidence: EvidenceItem[];
};

type AnalysisReviewSectionModel = {
  title: string;
  intent: string;
  items: AnalysisReviewItem[];
  empty: string;
};

function buildAnalysisReviewSections(analysis: JobAnalysisResponse): AnalysisReviewSectionModel[] {
  const fit = analysis.fit;
  const guidance = analysis.guidance;
  const job = analysis.parsed_job;
  return [
    {
      title: "Why Apply",
      intent: "Positive evidence for spending time on this role.",
      items: buildReviewItems(
        guidance.apply_reasoning.length ? guidance.apply_reasoning : fit.strong_matches,
        guidance.apply_reasoning.length
          ? guidance.evidence?.apply_reasoning ?? []
          : [...(fit.evidence?.strong_matches ?? []), ...(fit.evidence?.recommendation ?? [])]
      ),
      empty: "No strong apply reason was generated yet."
    },
    {
      title: "Risks and Concerns",
      intent: "Reasons to verify fit before investing more effort.",
      items: buildReviewItems(dedupeAnalysisItems(fit.concerns), fit.evidence?.concerns ?? []),
      empty: "No major risks detected yet."
    },
    {
      title: "Skill Gaps",
      intent: "Missing hard requirements to validate and prepare.",
      items: buildReviewItems(fit.gaps, fit.evidence?.gaps ?? []),
      empty: "No skill gaps detected yet."
    },
    {
      title: "Growth Areas",
      intent: "Preferred, optional, or useful areas to strengthen without treating them as blockers.",
      items: buildReviewItems(dedupeAnalysisItems(fit.growth_areas ?? []), []),
      empty: "No optional growth areas detected yet."
    },
    {
      title: "Prep Actions",
      intent: "Concrete actions that can turn analysis into preparation.",
      items: buildReviewItems(guidance.prep_plan, guidance.evidence?.prep_plan ?? []),
      empty: "No preparation actions generated yet."
    },
    {
      title: "Resume Positioning",
      intent: "Truthful emphasis points for tailoring your resume.",
      items: buildReviewItems(guidance.resume_guidance, guidance.evidence?.resume_guidance ?? []),
      empty: "No resume guidance generated yet."
    },
    {
      title: "Interview Focus",
      intent: "Likely areas to practice for screens and onsite loops.",
      items: buildReviewItems(guidance.interview_focus, guidance.evidence?.interview_focus ?? []),
      empty: "No interview focus generated yet."
    },
    {
      title: "Role Signals",
      intent: "Parsed job facts that explain the recommendation.",
      items: buildReviewItems([
        ...(job.team_business ? [`Team/business: ${job.team_business}`] : []),
        ...(job.role_focus ?? []),
        ...(job.requirements ?? []),
        ...(job.accepted_skill_alternatives ?? []),
        ...(job.responsibilities ?? [])
      ], []),
      empty: "No detailed role signals were extracted yet."
    }
  ];
}

function buildReviewItems(items: string[], evidenceItems: EvidenceItem[]): AnalysisReviewItem[] {
  const dedupedEvidence = dedupeEvidenceItems(evidenceItems);
  const usedEvidenceKeys = new Set<string>();
  return items.map((item, index) => {
    const directMatches = dedupedEvidence.filter((evidence) => {
      const key = evidenceKey(evidence);
      return !usedEvidenceKeys.has(key) && evidenceMatchesItem(evidence, item);
    });
    const fallback = directMatches.length
      ? []
      : dedupedEvidence[index] && !usedEvidenceKeys.has(evidenceKey(dedupedEvidence[index]))
        ? [dedupedEvidence[index]]
        : [];
    const evidence = [...directMatches, ...fallback].slice(0, 2);
    evidence.forEach((entry) => usedEvidenceKeys.add(evidenceKey(entry)));
    return {
      text: item,
      evidence
    };
  });
}

function dedupeEvidenceItems(items: EvidenceItem[]): EvidenceItem[] {
  const seen = new Set<string>();
  const deduped: EvidenceItem[] = [];
  for (const item of items) {
    const key = evidenceKey(item);
    if (!seen.has(key)) {
      seen.add(key);
      deduped.push(item);
    }
  }
  return deduped;
}

function evidenceKey(item: EvidenceItem): string {
  return [item.claim, item.evidence_from_job, item.profile_signal, item.severity, item.confidence]
    .map((value) => (value ?? "").trim().toLowerCase())
    .join("|");
}

function dedupeAnalysisItems(items: string[]): string[] {
  const deduped: string[] = [];
  for (const item of items) {
    const normalized = item.trim();
    if (!normalized) {
      continue;
    }
    const tokens = meaningfulAnalysisTokens(normalized);
    const alreadyIncluded = deduped.some((existing) => {
      const existingTokens = meaningfulAnalysisTokens(existing);
      const overlap = tokens.filter((token) => existingTokens.includes(token));
      const denominator = Math.min(tokens.length, existingTokens.length);
      return denominator > 0 && overlap.length / denominator >= 0.6;
    });
    if (!alreadyIncluded) {
      deduped.push(normalized);
    }
  }
  return deduped;
}

function meaningfulAnalysisTokens(value: string): string[] {
  const ignored = new Set(["role", "may", "include", "require", "requires", "significant", "work", "development", "heavy"]);
  return Array.from(
    new Set(
      value
        .toLowerCase()
        .split(/[^a-z0-9#+]+/)
        .filter((token) => token.length >= 4 && !ignored.has(token))
    )
  );
}

function evidenceMatchesItem(evidence: EvidenceItem, item: string): boolean {
  const claim = evidence.claim?.toLowerCase().trim();
  const text = item.toLowerCase().trim();
  return Boolean(claim && (text.includes(claim) || claim.includes(text) || sharedMeaningfulToken(claim, text)));
}

function sharedMeaningfulToken(first: string, second: string): boolean {
  const tokens = first.split(/[^a-z0-9#+]+/).filter((token) => token.length >= 4 || ["c++", "c#"].includes(token));
  return tokens.some((token) => second.includes(token));
}

function buildPrepFocus(analysis: JobAnalysisResponse): string {
  const values = [
    ...(analysis.fit.gaps ?? []),
    ...(analysis.guidance.prep_plan ?? []),
    ...(analysis.guidance.interview_focus ?? [])
  ];
  return values.length
    ? values.slice(0, 10).join("\n")
    : `Prepare for ${analysis.parsed_job.title || "this role"} with backend system design, coding practice, and role-specific gaps.`;
}

function buildResumeNotes(analysis: JobAnalysisResponse): string {
  const values = [
    ...(analysis.guidance.resume_guidance ?? []),
    ...(analysis.fit.strong_matches ?? []),
    ...(analysis.fit.transition_notes ?? [])
  ];
  return values.length
    ? values.slice(0, 10).join("\n")
    : `Tailor resume for ${analysis.parsed_job.title || "this role"} using only truthful profile facts.`;
}

function AnalysisResult({
  analysis,
  onCreatePrepPlan,
  onGenerateResume,
  onSave,
  onApplyUpdate,
  refreshContext,
  savePending,
  applyUpdatePending,
  sourceUrl
}: {
  analysis: JobAnalysisResponse;
  onCreatePrepPlan: () => void;
  onGenerateResume: () => void;
  onSave: () => void;
  onApplyUpdate: () => void;
  refreshContext: AnalysisRefreshContext | null;
  savePending: boolean;
  applyUpdatePending: boolean;
  sourceUrl: string | null;
}) {
  const job = analysis.parsed_job;
  const fit = analysis.fit;
  const [chatMessage, setChatMessage] = useState("");
  const [useWebSearch, setUseWebSearch] = useState(false);
  const [messages, setMessages] = useState<JobChatMessage[]>([]);
  const [feedbackType, setFeedbackType] = useState<AnalysisFeedbackType>("accurate");
  const [feedbackNote, setFeedbackNote] = useState("");
  const reviewSections = buildAnalysisReviewSections(analysis);
  const chatMutation = useMutation({
    mutationFn: (content: string) =>
      sendAssistantChat({
        focus: {
          type: "analysis_preview",
          analysis,
          source_url: sourceUrl
        },
        message: content,
        history: messages,
        use_web_search: useWebSearch
      }),
    onSuccess: (response) => {
      setMessages(response.messages);
      setChatMessage("");
    }
  });
  const feedbackMutation = useMutation({
    mutationFn: () =>
      saveAnalysisFeedback({
        analysis,
        feedback_type: feedbackType,
        note: feedbackNote.trim() || null,
        source_url: sourceUrl
      }),
    onSuccess: () => setFeedbackNote("")
  });

  function submitAnalysisChat() {
    const trimmed = chatMessage.trim();
    if (!trimmed || chatMutation.isPending) {
      return;
    }
    setChatMessage("");
    setMessages((current) => [
      ...current,
      {
        id: -Date.now(),
        job_id: 0,
        role: "user",
        content: trimmed,
        used_web_search: false,
        citations: []
      }
    ]);
    chatMutation.mutate(trimmed);
  }

  function askAbout(sectionTitle: string) {
    setChatMessage(`Review the "${sectionTitle}" section. Is it well supported by the job description and my profile? Point out anything too generic, missing, or unsupported.`);
  }

  return (
    <section className="flex max-h-[calc(100vh-140px)] min-h-[720px] flex-col rounded-lg border border-slate-200 bg-white shadow-panel">
      <div className="border-b border-slate-200 bg-white pb-3">
        <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase text-slate-500">Analysis Review</p>
            <h3 className="mt-1 text-xl font-semibold text-slate-950">{job.title || "Untitled job"}</h3>
            <p className="mt-1 text-sm text-slate-500">
              {job.company || "Unknown company"}
              {job.location ? ` · ${job.location}` : ""}
            </p>
          </div>
          <RecommendationBadge fit={fit} />
        </div>
        <div className="grid gap-3 px-4 sm:grid-cols-3">
          <button
            className="primary-button justify-center"
            type="button"
            disabled={refreshContext ? applyUpdatePending : savePending || Boolean(analysis.saved_job)}
            onClick={refreshContext ? onApplyUpdate : onSave}
          >
            {(refreshContext ? applyUpdatePending : savePending) ? <Loader2 className="animate-spin" size={18} /> : <BriefcaseBusiness size={18} />}
            {refreshContext ? "Confirm update" : analysis.saved_job ? "Saved" : "Save job"}
          </button>
          <button className="secondary-button justify-center" type="button" onClick={onCreatePrepPlan}>
            <CalendarCheck size={18} />
            Create prep plan
          </button>
          <button className="secondary-button justify-center" type="button" onClick={onGenerateResume}>
            <FileText size={18} />
            Draft resume
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50/70 p-4">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h4 className="text-sm font-semibold text-slate-950">Decision Summary</h4>
          <p className="mt-2 text-sm leading-6 text-slate-700">{fit.summary}</p>
          {fit.transition_notes.length ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {fit.transition_notes.slice(0, 3).map((note, index) => (
                <DataPill key={`transition-${index}`}>
                  {note}
                </DataPill>
              ))}
            </div>
          ) : null}
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {reviewSections.map((section) => (
            <AnalysisReviewSection
              key={section.title}
              section={section}
              onAsk={() => askAbout(section.title)}
            />
          ))}
        </div>

        <details className="mt-4 rounded-lg border border-slate-200 bg-white p-3">
          <summary className="cursor-pointer text-sm font-semibold text-slate-800">Execution details</summary>
          <div className="mt-3 grid gap-2 text-xs leading-5 text-muted">
            <p>{analysis.parser_used === "llm" ? "Parsed with LLM structured extraction." : parserFallbackLabel(analysis)}</p>
            <p>Semantic fit evaluated by LLM.</p>
            <p>{analysis.guidance_used === "llm" ? "Application guidance generated by LLM." : guidanceFallbackLabel(analysis)}</p>
          </div>
          <AnalysisWorkflowTrace analysis={analysis} />
        </details>

        <AnalysisFeedbackControls
          feedbackType={feedbackType}
          note={feedbackNote}
          onFeedbackTypeChange={setFeedbackType}
          onNoteChange={setFeedbackNote}
          onSubmit={() => feedbackMutation.mutate()}
          pending={feedbackMutation.isPending}
          saved={feedbackMutation.isSuccess}
          error={feedbackMutation.error}
        />

        <AssistantChatPanel
          chatError={chatMutation.error}
          contextLabel="Focus: analysis preview"
          emptyText="Ask why a concern was generated, whether a gap is real, or what to verify with web search."
          isPending={chatMutation.isPending}
          message={chatMessage}
          messages={messages}
          onMessageChange={setChatMessage}
          onSubmit={submitAnalysisChat}
          setUseWebSearch={setUseWebSearch}
          subtitle="Use this before saving to question concerns, ask for evidence, or request clarification."
          title="Ask About This Analysis"
          useWebSearch={useWebSearch}
        />
      </div>
    </section>
  );
}

function AnalysisWorkflowTrace({ analysis }: { analysis: JobAnalysisResponse }) {
  if (!analysis.workflow_graph && !analysis.workflow_run) {
    return null;
  }
  return (
    <section className="mt-4 rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h4 className="text-sm font-semibold text-slate-950">Workflow Trace</h4>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            Observable analysis stages from input preparation through guidance generation.
          </p>
        </div>
        {analysis.workflow_run ? <StatusPill status={analysis.workflow_run.status} /> : null}
      </div>
      {analysis.workflow_graph ? <WorkflowGraphPreview graph={analysis.workflow_graph} /> : null}
      {analysis.workflow_run?.tasks?.length ? (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {analysis.workflow_run.tasks.map((task) => (
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5" key={task.id}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-bold text-slate-900">{task.id.replace(/_/g, " ")}</span>
                <span className="rounded border border-slate-200 bg-white px-1.5 py-0.5 font-semibold text-slate-600">
                  {task.model_tier}
                </span>
              </div>
              <p className="mt-1 text-slate-600">{task.description}</p>
              {task.dependencies.length ? (
                <p className="mt-1 text-slate-500">Depends on {task.dependencies.map((value) => value.replace(/_/g, " ")).join(", ")}</p>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
      {analysis.workflow_run?.trace_events.length ? <WorkflowTraceTimeline events={analysis.workflow_run.trace_events} /> : null}
    </section>
  );
}

function AnalysisReviewSection({
  section,
  onAsk
}: {
  section: AnalysisReviewSectionModel;
  onAsk: () => void;
}) {
  const values = section.items.length > 0 ? section.items : [{ text: section.empty, evidence: [] }];
  return (
    <section className="min-w-0 rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold text-slate-950">{section.title}</h4>
          <p className="mt-1 text-xs leading-5 text-slate-500">{section.intent}</p>
        </div>
        <button className="icon-button" type="button" onClick={onAsk} aria-label={`Ask about ${section.title}`}>
          <MessageCircle size={17} />
        </button>
      </div>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-5 text-slate-700">
        {values.map((item, index) => (
          <li className={section.items.length ? "" : "text-muted"} key={`${section.title}-${index}`}>
            <span>{item.text}</span>
            {item.evidence.length > 0 ? (
              <div className="mt-2 space-y-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-2 text-xs leading-5 text-slate-700">
                {item.evidence.slice(0, 2).map((evidence, evidenceIndex) => (
                  <div key={`${section.title}-${index}-evidence-${evidenceIndex}`}>
                    {evidence.evidence_from_job ? <p><strong>Job evidence:</strong> {evidence.evidence_from_job}</p> : null}
                    {evidence.profile_signal ? <p><strong>Profile:</strong> {evidence.profile_signal}</p> : null}
                    {evidence.profile_source_path ? (
                      <p className="text-slate-600">
                        <strong>Profile source:</strong> {evidence.profile_source_path}
                        {evidence.profile_evidence ? ` · ${evidence.profile_evidence}` : ""}
                      </p>
                    ) : null}
                    <p className="text-slate-600">
                      {[evidence.severity, evidence.confidence ? `${evidence.confidence} confidence` : null].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                ))}
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function AnalysisFeedbackControls({
  feedbackType,
  note,
  onFeedbackTypeChange,
  onNoteChange,
  onSubmit,
  pending,
  saved,
  error
}: {
  feedbackType: AnalysisFeedbackType;
  note: string;
  onFeedbackTypeChange: (value: AnalysisFeedbackType) => void;
  onNoteChange: (value: string) => void;
  onSubmit: () => void;
  pending: boolean;
  saved: boolean;
  error: unknown;
}) {
  const options: Array<{ value: AnalysisFeedbackType; label: string }> = [
    { value: "accurate", label: "Accurate" },
    { value: "missing_gap", label: "Missing gap" },
    { value: "wrong_concern", label: "Wrong concern" },
    { value: "too_generic", label: "Too generic" },
    { value: "other", label: "Other" }
  ];
  return (
    <section className="mt-4 rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h4 className="text-sm font-semibold text-slate-950">Analysis Feedback</h4>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            Store review signals locally so future prompt changes and eval cases can learn from real misses.
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          {options.map((option) => (
            <button
              className={`min-h-9 rounded-md border px-2.5 text-xs font-semibold ${
                feedbackType === option.value ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 bg-slate-50 text-slate-700 hover:bg-white"
              }`}
              key={option.value}
              type="button"
              onClick={() => onFeedbackTypeChange(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
      <textarea
        className="mt-3 min-h-20 w-full resize-y rounded-md border border-slate-300 bg-white p-3 text-sm leading-5 text-slate-950 outline-none transition focus:border-slate-900 focus:ring-4 focus:ring-slate-900/10"
        value={note}
        onChange={(event) => onNoteChange(event.target.value)}
        placeholder="Optional: what should the analysis have said differently?"
      />
      {error ? <Feedback notice={null} error={formatUnknownError(error)} /> : null}
      {saved && !error ? <Feedback notice="Saved feedback locally." error={null} /> : null}
      <div className="mt-3 flex justify-end">
        <button className="secondary-button" type="button" disabled={pending} onClick={onSubmit}>
          {pending ? <Loader2 className="animate-spin" size={18} /> : <CheckCircle2 size={18} />}
          Save feedback
        </button>
      </div>
    </section>
  );
}

function AssistantChatPanel({
  chatError,
  contextLabel,
  emptyText,
  isPending,
  message,
  messages,
  onMessageChange,
  onSubmit,
  setUseWebSearch,
  subtitle,
  title,
  useWebSearch
}: {
  chatError: unknown;
  contextLabel: string;
  emptyText: string;
  isPending: boolean;
  message: string;
  messages: JobChatMessage[];
  onMessageChange: (value: string) => void;
  onSubmit: () => void;
  setUseWebSearch: (value: boolean) => void;
  subtitle: string;
  title: string;
  useWebSearch: boolean;
}) {
  return (
    <section className="mt-4 rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">{contextLabel}</p>
          <h4 className="mt-1 text-sm font-semibold text-slate-950">{title}</h4>
          <p className="mt-1 text-xs leading-5 text-slate-500">{subtitle}</p>
        </div>
        <label className="inline-flex min-h-9 items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 text-xs font-semibold text-slate-700">
          <input
            className="h-4 w-4 accent-teal-700"
            type="checkbox"
            checked={useWebSearch}
            onChange={(event) => setUseWebSearch(event.target.checked)}
          />
          Web search
        </label>
      </div>

      <div className="mt-3 max-h-72 space-y-2 overflow-y-auto pr-1">
        {messages.length === 0 ? <EmptyState text={emptyText} /> : null}
        {messages.map((chat) => (
          <ChatBubble key={`${chat.role}-${chat.id ?? chat.content}`} message={chat} />
        ))}
        {isPending ? <StreamingAssistantBubble answer="" statuses={["Reviewing analysis context"]} /> : null}
      </div>

      {chatError ? (
        <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">
          {formatUnknownError(chatError)}
        </div>
      ) : null}

      <div className="mt-3 flex flex-col gap-2">
        <textarea
          className="min-h-20 w-full resize-y rounded-md border border-slate-300 bg-white p-3 text-sm leading-5 text-slate-950 outline-none transition focus:border-slate-900 focus:ring-4 focus:ring-slate-900/10"
          value={message}
          onChange={(event) => onMessageChange(event.target.value)}
          placeholder="Example: Why did you say this may be research-oriented? What evidence supports that?"
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs leading-5 text-muted">
            {useWebSearch ? "Web search can add current company or team context." : "Web search is off; answer uses the analysis and job text."}
          </p>
          <button className="secondary-button" type="button" disabled={isPending || !message.trim()} onClick={onSubmit}>
            {isPending ? <Loader2 className="animate-spin" size={18} /> : <Send size={18} />}
            Ask
          </button>
        </div>
      </div>
    </section>
  );
}

function JobTracker({
  jobs,
  isLoading,
  selectedJobId,
  onRefresh,
  onSelect,
  onStatusChange,
  onDelete
}: {
  jobs: JobRecord[];
  isLoading: boolean;
  selectedJobId: number | null;
  onRefresh: () => void;
  onSelect: (jobId: number) => void;
  onStatusChange: (jobId: number, status: ApplicationStatus) => void;
  onDelete: (jobId: number) => void;
}) {
  const [companyFilter, setCompanyFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<ApplicationStatus | "all">("all");
  const companyOptions = useMemo(() => {
    const companies = jobs
      .map((job) => job.company?.trim())
      .filter((company): company is string => Boolean(company));
    return Array.from(new Set(companies)).sort((first, second) => first.localeCompare(second));
  }, [jobs]);
  const filteredJobs = useMemo(() => {
    return jobs.filter((job) => {
      const matchesCompany = companyFilter === "all" || job.company === companyFilter;
      const matchesStatus = statusFilter === "all" || job.status === statusFilter;
      return matchesCompany && matchesStatus;
    });
  }, [companyFilter, jobs, statusFilter]);
  const hasActiveFilters = companyFilter !== "all" || statusFilter !== "all";

  return (
    <Panel>
      <div className="flex items-start justify-between gap-3">
        <SectionTitle
          icon={<BriefcaseBusiness size={20} />}
          title="Application Tracker"
          subtitle="Saved jobs, links, status, and revisit-ready analysis."
        />
        <button className="icon-button" type="button" onClick={onRefresh} aria-label="Refresh saved jobs">
          <RefreshCw size={18} />
        </button>
      </div>

      <div className="mt-4 grid gap-3 border-y border-slate-200 bg-slate-50/80 px-3 py-3 lg:grid-cols-[minmax(0,1fr)_220px_220px_auto] lg:items-end">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase text-slate-500">Filters</p>
          <p className="mt-1 text-sm text-slate-600">
            Showing {filteredJobs.length} of {jobs.length} saved {jobs.length === 1 ? "job" : "jobs"}.
          </p>
        </div>
        <label className="block min-w-0">
          <span className="text-xs font-semibold text-slate-600">Company</span>
          <select
            className="select mt-1 w-full"
            value={companyFilter}
            onChange={(event) => setCompanyFilter(event.target.value)}
            disabled={jobs.length === 0}
          >
            <option value="all">All companies</option>
            {companyOptions.map((company) => (
              <option key={company} value={company}>
                {company}
              </option>
            ))}
          </select>
        </label>
        <label className="block min-w-0">
          <span className="text-xs font-semibold text-slate-600">Status</span>
          <select
            className="select mt-1 w-full"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as ApplicationStatus | "all")}
            disabled={jobs.length === 0}
          >
            <option value="all">All statuses</option>
            {statuses.map((status) => (
              <option key={status} value={status}>
                {titleCase(status)}
              </option>
            ))}
          </select>
        </label>
        <button
          className="secondary-button justify-center"
          type="button"
          disabled={!hasActiveFilters}
          onClick={() => {
            setCompanyFilter("all");
            setStatusFilter("all");
          }}
        >
          Clear filters
        </button>
      </div>

      <div className="mt-4 grid gap-3">
        {isLoading ? <EmptyState text="Loading saved jobs..." /> : null}
        {!isLoading && jobs.length === 0 ? <EmptyState text="No saved jobs yet." /> : null}
        {!isLoading && jobs.length > 0 && filteredJobs.length === 0 ? <EmptyState text="No saved jobs match the current filters." /> : null}
        {filteredJobs.map((job) => (
          <JobCard
            key={job.id}
            job={job}
            selected={selectedJobId === job.id}
            onSelect={() => onSelect(job.id)}
            onStatusChange={(status) => onStatusChange(job.id, status)}
            onDelete={() => onDelete(job.id)}
          />
        ))}
      </div>
    </Panel>
  );
}

function JobCard({
  job,
  selected,
  onSelect,
  onStatusChange,
  onDelete
}: {
  job: JobRecord;
  selected: boolean;
  onSelect: () => void;
  onStatusChange: (status: ApplicationStatus) => void;
  onDelete: () => void;
}) {
  const summary = buildTrackerSummary(job);

  return (
    <article
      className={`rounded-lg border bg-white p-4 transition ${
        selected ? "border-slate-900 shadow-[0_0_0_3px_rgba(15,23,42,0.12)]" : "border-slate-200 hover:border-slate-300"
      }`}
    >
      <button className="block w-full text-left" type="button" onClick={onSelect}>
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-slate-950">{job.title || "Untitled job"}</h3>
            <p className="mt-1 text-xs text-slate-500">
              {job.company || "Unknown company"}
              {job.location ? ` · ${job.location}` : ""}
            </p>
          </div>
          <div className="flex flex-wrap items-start gap-2 lg:justify-end">
            <RecommendationBadge fit={{ score: job.fit_score, priority: job.priority } as JobFit} compact />
            <Badge>
              {applicationTypeLabel(job.application_type)}
            </Badge>
          </div>
        </div>

        {summary.team ? (
          <DataPill className="mt-3">
            <Users size={14} />
            {summary.team}
          </DataPill>
        ) : null}

        <div className="mt-3 grid gap-2 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
          <p className="text-sm leading-5 text-slate-700">
            <span className="font-semibold text-slate-950">Team business: </span>
            {summary.business}
          </p>
          <p className="text-sm leading-5 text-slate-700">
            <span className="font-semibold text-slate-950">Role: </span>
            {summary.description}
          </p>
        </div>

        {summary.techStack.length > 0 ? (
          <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Highlighted tech stack">
            {summary.techStack.map((skill) => (
              <DataPill key={skill}>
                {skill}
              </DataPill>
            ))}
          </div>
        ) : null}
      </button>

      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto_auto] sm:items-center">
        <select
          className="select"
          value={job.status}
          onChange={(event) => onStatusChange(event.target.value as ApplicationStatus)}
          aria-label={`Application status for ${job.title || "job"}`}
        >
          {statuses.map((status) => (
            <option key={status} value={status}>
              {titleCase(status)}
            </option>
          ))}
        </select>
        {job.source_url ? (
          <a className="link-button" href={job.source_url} target="_blank" rel="noreferrer">
            <ExternalLink size={16} />
            Open
          </a>
        ) : null}
        <button className="danger-button" type="button" onClick={onDelete}>
          <Trash2 size={16} />
          Delete
        </button>
      </div>
    </article>
  );
}

function JobDetailDrawer({
  detail,
  isLoading,
  isRegenerating,
  onRegenerate,
  onClose
}: {
  detail?: JobDetail;
  isLoading: boolean;
  isRegenerating: boolean;
  onRegenerate: (job: JobRecord) => void;
  onClose: () => void;
}) {
  const analysis = detail?.analysis;
  const job = detail?.job;

  return (
    <div className="fixed inset-0 z-40 bg-slate-950/35 backdrop-blur-sm">
      <aside className="ml-auto flex h-full w-full max-w-[1240px] flex-col border-l border-slate-200 bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-slate-200 p-4">
          <SectionTitle icon={<BookOpenCheck size={20} />} title="Saved Analysis" subtitle="Job detail, guidance, and scoped chat." />
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close saved analysis">
            <X size={18} />
          </button>
        </div>

        <div className="grid min-h-0 flex-1 gap-0 lg:grid-cols-[minmax(0,1fr)_420px]">
        <div className="overflow-y-auto bg-slate-50/70 p-4">
        {isLoading ? <EmptyState text="Loading saved analysis..." /> : null}
        {job && !isLoading ? (
          <div>
            <div className="flex flex-col gap-3 border-b border-slate-200 bg-white p-4 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h3 className="text-lg font-semibold text-slate-950">{job.title || "Untitled job"}</h3>
                <p className="mt-1 text-sm text-slate-500">
                  {job.company || "Unknown company"}
                  {job.location ? ` · ${job.location}` : ""}
                </p>
              </div>
              <RecommendationBadge fit={{ score: job.fit_score, priority: job.priority } as JobFit} />
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-3">
              {job.source_url ? (
                <a className="link-button" href={job.source_url} target="_blank" rel="noreferrer">
                  <ExternalLink size={16} />
                  Open original job link
                </a>
              ) : null}
              <button
                className="secondary-button"
                type="button"
                disabled={isRegenerating || !job.source_url}
                onClick={() => onRegenerate(job)}
                title={job.source_url ? "Fetch the source link and review a refreshed analysis before updating this saved job" : "This job has no saved source link"}
              >
                {isRegenerating ? <Loader2 className="animate-spin" size={16} /> : <RefreshCw size={16} />}
                {isRegenerating ? "Starting refresh..." : "Refresh analysis"}
              </button>
            </div>

            {analysis ? (
              <div className="mt-4">
                <Panel>
                  <h4 className="text-sm font-semibold text-slate-950">Decision summary</h4>
                  <p className="mt-2 text-sm leading-6 text-slate-700">{analysis.fit.summary}</p>
                </Panel>
                <AnalysisSections fit={analysis.fit} guidance={analysis.guidance} parsedJob={analysis.parsed_job} singleColumn />
              </div>
            ) : (
              <EmptyState text="No saved analysis payload for this job yet. Re-analyze the job to refresh stored details." />
            )}
          </div>
        ) : null}
        </div>
        <div className="min-h-0 border-t border-slate-200 bg-white p-4 lg:border-l lg:border-t-0">
          {job && !isLoading ? <JobChatPanel jobId={job.id} /> : null}
        </div>
        </div>
      </aside>
    </div>
  );
}

function JobChatPanel({ jobId }: { jobId: number }) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");
  const [useWebSearch, setUseWebSearch] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [sessionMessages, setSessionMessages] = useState<JobChatMessage[]>([]);
  const [streamingAnswer, setStreamingAnswer] = useState("");
  const [streamStatuses, setStreamStatuses] = useState<string[]>([]);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const chatQuery = useQuery({
    queryKey: ["jobs", jobId, "chat"],
    queryFn: () => listJobChat(jobId),
    enabled: showHistory
  });
  const clearHistoryMutation = useMutation({
    mutationFn: () => clearJobChat(jobId),
    onSuccess: async () => {
      setSessionMessages([]);
      await queryClient.invalidateQueries({ queryKey: ["jobs", jobId, "chat"] });
    }
  });

  async function submitChat() {
    const trimmed = message.trim();
    if (!trimmed || isStreaming) {
      return;
    }
    setMessage("");
    const userMessage: JobChatMessage = {
      id: -Date.now(),
      job_id: jobId,
      role: "user",
      content: trimmed,
      used_web_search: false,
      citations: []
    };
    setSessionMessages((current) => [...current, userMessage]);
    setStreamingAnswer("");
    setStreamStatuses([]);
    setStreamError(null);
    setIsStreaming(true);
    try {
      await streamJobChat(jobId, { message: trimmed, use_web_search: useWebSearch }, (event) => {
        if (event.type === "status") {
          setStreamStatuses((current) => [...current.slice(-3), event.message]);
        }
        if (event.type === "chunk") {
          setStreamingAnswer((current) => current + event.text);
        }
        if (event.type === "error") {
          setStreamError(event.message);
        }
        if (event.type === "done" && event.message) {
          setSessionMessages((current) => [...current, event.message as JobChatMessage]);
        }
      });
      await queryClient.invalidateQueries({ queryKey: ["jobs", jobId, "chat"] });
    } catch (error) {
      setStreamError(formatUnknownError(error));
    } finally {
      setIsStreaming(false);
      setStreamingAnswer("");
      setStreamStatuses([]);
    }
  }

  return (
    <section className="flex h-full min-h-[560px] flex-col rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex items-start gap-2">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-700">
          <MessageCircle size={18} />
        </div>
      <div>
          <h3 className="text-sm font-semibold text-slate-950">Ask About This Job</h3>
          <p className="mt-1 text-xs leading-5 text-slate-500">Questions use the saved job, analysis, profile, and local chat history.</p>
        </div>
      </div>

      <label className="mt-3 flex items-start gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-700">
        <input
          className="mt-0.5 h-4 w-4 accent-teal-700"
          type="checkbox"
          checked={useWebSearch}
          onChange={(event) => setUseWebSearch(event.target.checked)}
        />
        <span>
          Use web search for current company, interview, or product context
          <span className="block font-normal text-muted">Keep this off for fit, resume, and prep questions that only need saved context.</span>
        </span>
      </label>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <button className="secondary-button" type="button" onClick={() => setShowHistory((current) => !current)}>
          <Clock size={16} />
          {showHistory ? "Hide history" : "Load history"}
        </button>
        <button className="danger-button" type="button" onClick={() => clearHistoryMutation.mutate()}>
          <Trash2 size={16} />
          Clear
        </button>
      </div>

      <div className="mt-3 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {showHistory && chatQuery.isLoading ? <EmptyState text="Loading chat history..." /> : null}
        {!showHistory && sessionMessages.length === 0 ? (
          <EmptyState text="Fresh job chat. Load history only when you need earlier messages." />
        ) : null}
        {showHistory && !chatQuery.isLoading && (chatQuery.data ?? []).length === 0 ? (
          <EmptyState text="No saved chat history for this job yet." />
        ) : null}
        {(showHistory ? chatQuery.data ?? [] : sessionMessages).map((chatMessage) => (
          <ChatBubble key={chatMessage.id} message={chatMessage} />
        ))}
        {isStreaming ? <StreamingAssistantBubble answer={streamingAnswer} statuses={streamStatuses} /> : null}
      </div>

      {streamError ? (
        <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">
          {streamError}
        </div>
      ) : null}

      <div className="sticky bottom-0 -mx-3 mt-3 flex flex-col gap-2 border-t border-slate-200 bg-white/95 px-3 pb-1 pt-3 backdrop-blur">
        <textarea
          className="min-h-24 w-full resize-y rounded-md border border-slate-300 bg-white p-3 text-sm leading-5 text-slate-950 outline-none transition focus:border-slate-900 focus:ring-4 focus:ring-slate-900/10"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="Ask how to prepare, whether to apply, or how to position your experience..."
        />
        <button className="primary-button self-end" type="button" disabled={isStreaming || !message.trim()} onClick={submitChat}>
          {isStreaming ? <Loader2 className="animate-spin" size={18} /> : <Send size={18} />}
          Send
        </button>
      </div>
    </section>
  );
}

function StreamingAssistantBubble({ answer, statuses }: { answer: string; statuses: string[] }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[92%] rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm leading-5 text-slate-800">
        <div className="mb-2 space-y-1 border-b border-slate-200 pb-2">
          {statuses.length ? (
            statuses.map((status) => (
              <p className="flex items-center gap-2 text-xs font-semibold text-muted" key={status}>
                <Loader2 className="animate-spin" size={13} />
                {status}
              </p>
            ))
          ) : (
            <p className="flex items-center gap-2 text-xs font-semibold text-muted">
              <Loader2 className="animate-spin" size={13} />
              Starting response
            </p>
          )}
        </div>
        <MarkdownMessage content={answer || "Generating answer..."} />
      </div>
    </div>
  );
}

function ChatBubble({ message }: { message: JobChatMessage | GlobalChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[92%] rounded-lg px-3 py-2 text-sm leading-5 shadow-sm ${
          isUser ? "border border-slate-300 bg-slate-100 text-slate-950" : "border border-slate-200 bg-white text-slate-800"
        }`}
      >
        <MarkdownMessage content={message.content} />
        {message.citations.length > 0 ? (
          <div className="mt-2 border-t border-slate-200 pt-2">
            <p className="text-xs font-bold text-muted">Sources</p>
            <ul className="mt-1 space-y-1">
              {message.citations.map((citation) => (
                <li key={citation.url}>
                  <a
                    className="text-xs font-semibold text-slate-700 underline"
                    href={citation.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {citation.title || citation.url}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="prose-chat">
      <ReactMarkdown
        components={{
          a: ({ children, href }) => (
            <a className="font-semibold text-slate-900 underline" href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
          pre: ({ children }) => <pre className="my-2 overflow-x-auto rounded-md bg-slate-950 p-3 text-xs leading-5 text-slate-50">{children}</pre>
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function AnalysisSections({
  fit,
  guidance,
  parsedJob,
  singleColumn = false
}: {
  fit: JobFit;
  guidance: JobApplicationGuidance;
  parsedJob: ParsedJob;
  singleColumn?: boolean;
}) {
  const sections = useMemo<Array<[string, string[]]>>(
    () => [
      ["Apply reasoning", guidance.apply_reasoning],
      ["Prep plan", guidance.prep_plan],
      ["Resume guidance", guidance.resume_guidance],
      ["Learning plan", guidance.learning_plan],
      ["Interview focus", guidance.interview_focus],
      ["Strong matches", fit.strong_matches],
      ["Skill gaps", fit.gaps],
      ["Growth areas", fit.growth_areas ?? []],
      ["Concerns", fit.concerns],
      ["Transition notes", fit.transition_notes],
      ["Required skills", parsedJob.required_skills ?? []],
      ["Preferred skills", parsedJob.preferred_skills ?? []],
      ["Accepted skill alternatives", parsedJob.accepted_skill_alternatives ?? []],
      ["Qualifications to validate", parsedJob.ambiguous_qualifications ?? []],
      ["Responsibilities", parsedJob.responsibilities ?? []],
      ["Requirements", parsedJob.requirements ?? []]
    ],
    [fit, guidance, parsedJob]
  );

  return (
    <div className={`mt-4 grid gap-3 ${singleColumn ? "grid-cols-1" : "lg:grid-cols-2"}`}>
      {sections.map(([title, items]) => (
        <InfoList key={title} title={title} items={items} />
      ))}
    </div>
  );
}

function InfoList({ title, items }: { title: string; items: string[] }) {
  const values = items.length > 0 ? items : ["None detected yet"];
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-3">
      <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-5 text-slate-700">
        {values.map((item, index) => (
          <li key={`${title}-${index}`}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

function RecommendationBadge({ fit, compact = false }: { fit: JobFit; compact?: boolean }) {
  const tone =
    fit.priority === "high"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : fit.priority === "medium"
        ? "border-amber-200 bg-amber-50 text-amber-800"
        : "border-rose-200 bg-rose-50 text-rose-700";

  return (
    <div className={`inline-flex shrink-0 items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs font-semibold ${tone}`}>
      <span>{fit.score}</span>
      {!compact ? <span>{titleCase(fit.priority)} priority</span> : null}
    </div>
  );
}

function parserFallbackLabel(analysis: JobAnalysisResponse): string {
  return analysis.parser_warning
    ? `Parsed with deterministic fallback: ${analysis.parser_warning}`
    : "Parsed with deterministic rules.";
}

function guidanceFallbackLabel(analysis: JobAnalysisResponse): string {
  return analysis.guidance_warning
    ? `Application guidance unavailable: ${analysis.guidance_warning}`
    : "Application guidance was not requested.";
}

function applicationTypeLabel(value: JobRecord["application_type"]): string {
  return {
    internal_transfer: "Internal transfer",
    external_application: "External",
    unknown: "Unknown type"
  }[value];
}
