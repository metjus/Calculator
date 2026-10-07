// Thin fetch wrapper for the FastAPI backend (same origin; session cookie).

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
  }
}

type Json = Record<string, unknown> | unknown[];

function messageFrom(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{msg, loc}] — show the first, readable part.
    const first = detail[0] as { msg?: string } | undefined;
    return (first?.msg ?? fallback).replace(/^Value error, /, "");
  }
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  return fallback;
}

export async function api<T>(path: string, options: { method?: string; body?: Json | FormData } = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Requested-With": "webaudit" };
  let body: BodyInit | undefined;
  if (options.body instanceof FormData) {
    body = options.body;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  const response = await fetch(path, { method: options.method ?? (body ? "POST" : "GET"), headers, body, credentials: "same-origin" });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    throw new ApiError(response.status, messageFrom(detail, `Request failed (${response.status})`), detail);
  }
  return data as T;
}

// ------------------------------------------------------------------ types

export type Me = { email: string; workspace_id: number; workspace_name: string; local?: boolean; version?: string };

export type KeyState = {
  service: "pagespeed" | "claude" | "google_places";
  configured: boolean;
  last4: string | null;
  test_ok: boolean | null;
  test_message: string | null;
  tested_at: string | null;
};

export type Profile = { name: string; company_id: string; phone: string; email: string };
export type SettingsData = { keys: Record<KeyState["service"], KeyState>; profile: Profile; pdf_language: "sk" | "cs" | "en" };

export type AuditStatus = "queued" | "running" | "done" | "cancelled" | "failed";
export type Audit = {
  id: number;
  project: string | null;
  status: AuditStatus;
  cancel_requested: boolean;
  total: number;
  done_count: number;
  error_count: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type SiteState = "pending" | "running" | "ok" | "unreachable" | "protected" | "disallowed" | "invalid" | "cancelled";
export type Site = {
  id: number;
  position: number;
  input_url: string;
  final_url: string | null;
  company_name: string | null;
  state: SiteState;
  state_reason: string | null;
  step: string | null;
  score: number | null;
  category: Category | null;
  top_issue: string | null;
  issues: number;
};
/** Why a queued audit has not started: audits before it, or a worker that is not running. */
export type QueueInfo = { ahead: number; running_audit_id: number | null; worker: string; worker_error: string | null };
export type AuditDetail = Audit & { sites: Site[]; queue: QueueInfo | null };
export type Category = "critical" | "weak" | "ok" | "good";

export type CreateResult = {
  audit: Audit | null;
  invalid: { input: string; error: string }[];
  no_website_leads: number;
  skipped_duplicates: number;
};

export type CheckResult = { id: string; area: string; status: "pass" | "warn" | "fail" | "na"; summary: string; evidence: string[] };
export type ScanResult = {
  checks: CheckResult[];
  issues: { check_id: string; area: string; status: "warn" | "fail"; impact: number }[];
  screenshots: Record<string, string>;
  tech: { cms: string | null; cms_version: string | null; libraries: { name: string; version: string | null }[] };
  score: { total: number; category: Category; areas: { area: string; score: number }[] } | null;
};

export type Company = {
  id: number;
  name: string | null;
  url: string | null;
  domain: string | null;
  project: string | null;
  has_website: boolean;
  do_not_contact: boolean;
  manual_check: "contact" | "skip" | null;
  source: "google" | "osm" | "manual";
  created_at: string;
  last_score: number | null;
  last_audit_id: number | null;
};

export type Country = { code: string; name: string; language: string };
export type AreaSuggestion = {
  id: string;
  label: string;
  kind: "place" | "region";
  lat: number;
  lon: number;
  bbox: [number, number, number, number] | null;
  osm_relation: number | null;
};
export type SearchOptions = {
  countries: Country[];
  categories: { id: string; label: string }[];
  google_configured: boolean;
  osm_attribution: string;
  radius_km: { min: number; max: number; default: number };
  map_tile_url: string;
  map_attribution: string;
};
export type SearchParams = {
  country: string;
  area: AreaSuggestion;
  mode: "radius" | "region";
  radius_km: number;
  category_id: string | null;
  query: string | null;
  sources: ("google" | "osm")[];
};
export type Estimate = {
  google_configured: boolean;
  google_requests_max: number;
  price_per_1000: number;
  estimated_cost_usd: number;
  used_this_month: number;
  free_per_month: number;
  over_free_limit: boolean;
  message: string;
};
export type SearchResult = {
  key: string;
  name: string;
  osm_name: string | null;
  website: string | null;
  domain: string | null;
  category: string | null;
  lat: number;
  lon: number;
  distance_km: number | null;
  place_id: string | null;
  osm_id: string | null;
  sources: ("google" | "osm")[];
  known: { company_id: number; do_not_contact: boolean; last_audit_at: string | null } | null;
};
export type SearchResponse = {
  results: SearchResult[];
  counts: { total: number; with_website: number; without_website: number };
  sources: { google: number; osm: number };
  attribution: string | null;
  warnings: string[];
};
export type SearchTemplate = { id: number; name: string; params: SearchParams };

export type ManualDecision = "contact" | "skip";
export type DashboardSite = {
  site_id: number;
  audit_id: number;
  domain: string;
  company: string | null;
  project: string | null;
  score: number;
  category: Category;
  top_issue: string | null;
  issues: number;
  issue_ids: string[];
  finished_at: string;
};
export type ManualSite = {
  site_id: number;
  audit_id: number;
  company_id: number | null;
  domain: string;
  url: string;
  company: string | null;
  project: string | null;
  state: SiteState;
  reason: string | null;
  decision: ManualDecision | null;
  checked_at: string | null;
  finished_at: string;
};
export type DashboardData = {
  projects: string[];
  metrics: { audited: number; to_check: number; average: number | null; critical: number; without_https: number };
  categories: Record<Category, number>;
  https: { yes: number; no: number };
  mobile: { yes: number; no: number };
  cms: { name: string; count: number }[];
  problems: { check_id: string; label: string; count: number }[];
  websites: DashboardSite[];
  manual: ManualSite[];
};

export type Problem = {
  check_id: string;
  area: string;
  area_label: string;
  status: "warn" | "fail";
  impact: number;
  label: string;
  problem: string;
  solution: string;
  summary: string;
  where: string[];
};
export type SiteView = {
  site: Site;
  audit: { id: number; project: string | null };
  company: { id: number; name: string | null; manual_check: ManualDecision | null } | null;
  finished_at: string | null;
  problems: Problem[];
  areas: { area: string; label: string; score: number | null; weight: number }[];
  facts: { label: string; value: string; tone: "bad" | "warn" | "ok" }[];
  contents: { label: string; value: string }[];
  history: { site_id: number; audit_id: number; state: SiteState; score: number | null; category: Category | null; finished_at: string }[];
  ai_review: AiReview | null;
  ai: AiEstimate;
  comparison: { self: Omit<CompareRow, "domain" | "url" | "state" | "score" | "category">; source: "competitors" | "audit"; rows: CompareRow[] };
  result: (ScanResult & { inventory?: { cookie_banner?: { detected: boolean; dismissed: boolean } } }) | null;
};

export type AiEstimate = {
  configured: boolean;
  model: string;
  sites: number;
  per_site_usd: { low: number; high: number };
  total_usd: { low: number; high: number };
};
export type AiReview = {
  status: "pass" | "warn" | "fail" | "na";
  summary: string;
  score?: number;
  verdict?: string;
  strengths?: string[];
  weaknesses?: string[];
  looks_dated?: boolean;
  language?: string;
  model?: string;
  cost_usd?: number;
};
export type CompareRow = {
  id?: number | null;
  site_id?: number;
  domain: string;
  url: string;
  state: SiteState | "pending";
  reason?: string | null;
  score: number | null;
  category: Category | null;
  screenshots?: string[];
  mobile: boolean | null;
  https: boolean | null;
  pagespeed: number | null;
  areas: Record<string, number>;
};
