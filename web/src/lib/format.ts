import type { AuditStatus, Category, SiteState } from "./api";

export const CATEGORY_LABEL: Record<Category, string> = { critical: "Critical", weak: "Weak", ok: "OK", good: "Good" };
export const CATEGORY_VAR: Record<Category, string> = { critical: "var(--crit)", weak: "var(--weak)", ok: "var(--ok)", good: "var(--good)" };

export const SITE_STATE_LABEL: Record<SiteState, string> = {
  pending: "Waiting",
  running: "Scanning",
  ok: "Scored",
  unreachable: "Not loaded",
  protected: "Protected – check manually",
  disallowed: "Not scanned (robots.txt)",
  invalid: "Invalid URL",
  cancelled: "Skipped",
};

export const AUDIT_STATUS_LABEL: Record<AuditStatus, string> = {
  queued: "Queued",
  running: "Running",
  done: "Finished",
  cancelled: "Stopped",
  failed: "Failed",
};

const dateFormat = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const timeFormat = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export function parseDate(value: string): Date {
  // The API returns UTC; SQLite drops the offset, so treat naive timestamps as UTC.
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
}

const dayFormat = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });

/** Day and time this year, day and year before that: the archive shows dates years old. */
export const formatDate = (value: string | null) => {
  if (!value) return "—";
  const date = parseDate(value);
  return (date.getFullYear() === new Date().getFullYear() ? dateFormat : dayFormat).format(date);
};

export const formatDay = (value: string | null) => (value ? dayFormat.format(parseDate(value)) : "—");
export const formatTime = (value: string) => timeFormat.format(parseDate(value));

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${Math.round(seconds % 60)} s`;
}

export function hostOf(url: string | null): string {
  if (!url) return "";
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** Dollar amounts for API cost estimates: cents below a dollar, whole cents above. */
export const usd = (value: number) => (value > 0 && value < 0.01 ? "< $0.01" : `$${value.toFixed(2)}`);
