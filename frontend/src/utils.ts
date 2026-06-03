import type { JobRecord, ParsedJob } from "./types";

const TEAM_PATTERNS = [
  /about the team\s+(.+?)(?=\s+(?:basic qualifications|preferred qualifications|why aws|inclusive team culture|mentorship|work\/life balance|description)\b)/i,
  /team\s*:\s*(.+?)(?=\s+(?:description|basic qualifications|preferred qualifications)\b)/i,
  /organization\s*:\s*(.+?)(?=\s+(?:description|basic qualifications|preferred qualifications)\b)/i
];

const BUSINESS_PATTERNS = [
  /about the team\s+(.+?)(?=\s+(?:basic qualifications|preferred qualifications|why aws|inclusive team culture|mentorship|work\/life balance|description|key job responsibilities)\b)/i,
  /about the org(?:anization)?\s+(.+?)(?=\s+(?:basic qualifications|preferred qualifications|description|key job responsibilities)\b)/i,
  /team overview\s+(.+?)(?=\s+(?:basic qualifications|preferred qualifications|description|key job responsibilities)\b)/i,
  /our team\s+(?:is|builds|owns|develops|operates|supports)\s+(.+?)(?=\s+(?:basic qualifications|preferred qualifications|description|key job responsibilities)\b)/i
];

const BUSINESS_KEYWORDS = [
  "business",
  "customers",
  "customer",
  "platform",
  "service",
  "product",
  "team",
  "organization",
  "infrastructure",
  "marketplace",
  "pricing",
  "payments",
  "ads",
  "commerce",
  "data",
  "analytics"
];

const DESCRIPTION_STARTERS = [
  "build",
  "design",
  "develop",
  "own",
  "lead",
  "create",
  "work on",
  "solve",
  "deliver",
  "drive"
];

const NOISY_DESCRIPTION_PREFIXES = [
  "skip to main content",
  "home",
  "teams",
  "locations",
  "job categories",
  "my career",
  "my applications",
  "my profile",
  "account security",
  "settings",
  "sign out",
  "resources",
  "apply now",
  "job details",
  "share this job",
  "join us on",
  "download our app"
];

const TECH_PRIORITY = [
  "kubernetes",
  "eks",
  "apache flink",
  "flink",
  "apache iceberg",
  "java",
  "python",
  "distributed systems",
  "aws",
  "cloud",
  "serverless",
  "lambda",
  "api",
  "rest apis",
  "cdc",
  "docker",
  "llm",
  "agent",
  "vector database",
  "fastapi"
];

const TECH_LABELS: Record<string, string> = {
  api: "APIs",
  aws: "AWS",
  cdc: "CDC",
  eks: "EKS",
  fastapi: "FastAPI",
  flink: "Apache Flink",
  "apache flink": "Apache Flink",
  "apache iceberg": "Apache Iceberg",
  java: "Java",
  kubernetes: "Kubernetes",
  lambda: "Lambda",
  llm: "LLM",
  python: "Python",
  "rest apis": "REST APIs"
};

export type TrackerSummary = {
  team: string | null;
  business: string;
  description: string;
  techStack: string[];
};

export function buildTrackerSummary(job: JobRecord): TrackerSummary {
  const parsedJob = job.analysis?.parsed_job;
  return {
    team: extractTeamName(job.description, parsedJob),
    business: summarizeTeamBusiness(job.description, parsedJob),
    description: summarizeRole(job.description, parsedJob),
    techStack: extractTechStack(job, parsedJob)
  };
}

export function summarize(description: string, maxLength = 180): string {
  const normalized = description.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "No description saved yet.";
  }

  const sentence = normalized.split(/(?<=[.!?])\s+/).find((item) => item.length > 80) ?? normalized;
  return truncate(sentence, maxLength);
}

export function truncate(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 1).trim()}...`;
}

function extractTeamName(description: string, parsedJob?: ParsedJob | null): string | null {
  if (parsedJob?.team_business) {
    return null;
  }

  const roleFocus = parsedJob?.role_focus?.find((item) => item.trim().length > 0);
  if (roleFocus) {
    return truncate(cleanSentence(roleFocus), 90);
  }

  const normalized = normalizeText(description);
  for (const pattern of TEAM_PATTERNS) {
    const match = normalized.match(pattern);
    const candidate = match?.[1]?.trim();
    if (candidate) {
      return truncate(cleanSentence(candidate), 90);
    }
  }

  return null;
}

function summarizeTeamBusiness(description: string, parsedJob?: ParsedJob | null): string {
  if (parsedJob?.team_business?.trim()) {
    return truncate(cleanSentence(parsedJob.team_business), 150);
  }

  const normalized = normalizeText(description);
  for (const pattern of BUSINESS_PATTERNS) {
    const match = normalized.match(pattern);
    const candidate = match?.[1]?.trim();
    if (candidate && isUsefulBusinessSentence(candidate)) {
      return truncate(cleanSentence(candidate), 150);
    }
  }

  const sourceItems = [
    ...(parsedJob?.role_focus ?? []),
    ...(parsedJob?.responsibilities ?? [])
  ];
  const structured = sourceItems.find((item) => isUsefulBusinessSentence(item));
  if (structured) {
    return truncate(cleanSentence(structured), 150);
  }

  const sentences = normalized
    .split(/(?<=[.!?])\s+/)
    .map(cleanSentence)
    .filter(Boolean);
  const candidate = sentences.find((sentence) => isUsefulBusinessSentence(sentence));
  return candidate ? truncate(candidate, 150) : "Team/business context not extracted yet.";
}

function summarizeRole(description: string, parsedJob?: ParsedJob | null): string {
  const sourceItems = [
    ...(parsedJob?.responsibilities ?? []),
    ...(parsedJob?.requirements ?? [])
  ];
  const structured = sourceItems.find((item) => isUsefulRoleSentence(item));
  if (structured) {
    return truncate(cleanSentence(structured), 170);
  }

  const normalized = normalizeText(description);
  const sentences = normalized
    .split(/(?<=[.!?])\s+/)
    .map(cleanSentence)
    .filter(Boolean);
  const candidate =
    sentences.find((sentence) => isUsefulRoleSentence(sentence)) ??
    sentences.find((sentence) => sentence.length >= 60 && !isNoisyDescription(sentence)) ??
    normalized;

  return truncate(candidate, 170);
}

function extractTechStack(job: JobRecord, parsedJob?: ParsedJob | null): string[] {
  const rawSkills = [
    ...job.skills,
    ...(parsedJob?.skills ?? []),
    ...(parsedJob?.required_skills ?? []),
    ...(parsedJob?.preferred_skills ?? [])
  ];
  const normalizedSkills = rawSkills
    .map((skill) => skill.trim())
    .filter(Boolean);
  const jobText = normalizeText(`${job.description} ${normalizedSkills.join(" ")}`).toLowerCase();

  const prioritized = TECH_PRIORITY
    .filter((tech) => normalizedSkills.some((skill) => skill.toLowerCase() === tech) || containsPhrase(jobText, tech))
    .map(labelTech);

  const remaining = normalizedSkills
    .map(labelTech)
    .filter((skill) => isLikelyTechSkill(skill));

  return dedupe([...prioritized, ...remaining]).slice(0, 6);
}

function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function cleanSentence(value: string): string {
  return normalizeText(value)
    .replace(/^[-*]\s*/, "")
    .replace(/^description\s*/i, "")
    .replace(/^about the team\s*/i, "")
    .replace(/^basic qualifications\s*/i, "")
    .replace(/^preferred qualifications\s*/i, "")
    .trim();
}

function isUsefulRoleSentence(sentence: string): boolean {
  const lowered = sentence.toLowerCase();
  return (
    sentence.length >= 45 &&
    !isNoisyDescription(sentence) &&
    DESCRIPTION_STARTERS.some((starter) => lowered.startsWith(starter) || lowered.includes(` ${starter} `))
  );
}

function isUsefulBusinessSentence(sentence: string): boolean {
  const lowered = sentence.toLowerCase();
  return (
    sentence.length >= 35 &&
    !isNoisyDescription(sentence) &&
    BUSINESS_KEYWORDS.some((keyword) => lowered.includes(keyword)) &&
    !DESCRIPTION_STARTERS.some((starter) => lowered.startsWith(starter))
  );
}

function isNoisyDescription(sentence: string): boolean {
  const lowered = sentence.toLowerCase();
  return NOISY_DESCRIPTION_PREFIXES.some((prefix) => lowered.startsWith(prefix));
}

function containsPhrase(text: string, phrase: string): boolean {
  const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(^|[^a-z0-9+#])${escaped}([^a-z0-9+#]|$)`, "i").test(text);
}

function labelTech(value: string): string {
  const normalized = value.trim().toLowerCase();
  return TECH_LABELS[normalized] ?? titleCase(value.trim());
}

function isLikelyTechSkill(skill: string): boolean {
  return (
    /^[A-Z0-9+#. -]{2,30}$/.test(skill) ||
    /api|aws|cloud|database|distributed|java|kubernetes|python|serverless|system/i.test(skill)
  );
}

function dedupe(values: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const key = value.toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      result.push(value);
    }
  }
  return result;
}

export function titleCase(value: string): string {
  return value
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((word) => `${word[0]?.toUpperCase() ?? ""}${word.slice(1)}`)
    .join(" ");
}
