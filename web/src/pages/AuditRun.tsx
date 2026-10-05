import { ChevronDown, ChevronRight, CircleAlert, CircleCheck, CircleX, ClipboardCopy, Info, LayoutDashboard, Plus, Square, SquareTerminal, TriangleAlert } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Banner, Button, Card, PageHeader, ProgressBar, ScoreBadge, Spinner, Tag } from "../components/ui";
import { api, type AuditDetail, type Site, type SiteState } from "../lib/api";
import { AUDIT_STATUS_LABEL, formatDuration, formatTime, hostOf, plural, SITE_STATE_LABEL } from "../lib/format";
import { useToast } from "../lib/toast";
import { useApi } from "../lib/useApi";

type Level = "ok" | "warn" | "error" | "info";
type LogLine = { id: number; time: string; level: Level; url?: string; message: string };
type Current = { position: number; url: string; step: string };
type DoneSummary = { status: string; total: number; done: number; errors: number; scored: number; average: number | null; duration_s: number };

const LEVEL_ICON = { ok: CircleCheck, warn: TriangleAlert, error: CircleX, info: Info };
const LEVEL_LABEL = { ok: "Done", warn: "Warning", error: "Error", info: "Info" };
const STATE_COLOR: Partial<Record<SiteState, string>> = {
  running: "var(--accent)",
  ok: "var(--good)",
  unreachable: "var(--crit)",
  invalid: "var(--crit)",
  protected: "var(--weak)",
  disallowed: "var(--weak)",
  cancelled: "var(--neutral)",
};

export function AuditRun() {
  const { id } = useParams();
  const toast = useToast();
  const detail = useApi<AuditDetail>(`/api/audits/${id}`);
  const [log, setLog] = useState<LogLine[]>([]);
  const [current, setCurrent] = useState<Current | null>(null);
  const [summary, setSummary] = useState<DoneSummary | null>(null);
  const [stopping, setStopping] = useState(false);
  const reloadTimer = useRef<number | undefined>(undefined);
  const { reload, setData } = detail;

  useEffect(() => {
    setLog([]);
    setSummary(null);
    const source = new EventSource(`/api/audits/${id}/events`);
    const parse = (event: MessageEvent) => ({ id: Number(event.lastEventId), ...JSON.parse(event.data) });
    const scheduleReload = () => {
      window.clearTimeout(reloadTimer.current);
      reloadTimer.current = window.setTimeout(() => void reload(), 400);
    };
    const patchSite = (siteId: number, patch: Partial<Site>) =>
      setData((d) => (d ? { ...d, sites: d.sites.map((s) => (s.id === siteId ? { ...s, ...patch } : s)) } : d));

    source.addEventListener("step", (e) => {
      const data = parse(e as MessageEvent);
      setCurrent({ position: data.position, url: data.url, step: data.message });
      patchSite(data.site_id, { state: "running", step: data.message });
    });
    source.addEventListener("log", (e) => {
      const data = parse(e as MessageEvent);
      setLog((lines) => [...lines, { id: data.id, time: data.time, level: data.level ?? "info", url: data.url, message: data.message }]);
    });
    source.addEventListener("site_done", (e) => {
      const data = parse(e as MessageEvent);
      setLog((lines) => [...lines, { id: data.id, time: data.time, level: data.level, url: data.url, message: data.message ?? "" }]);
      patchSite(data.site_id, { state: data.state, score: data.score, category: data.category, step: null });
      scheduleReload();
    });
    source.addEventListener("audit_started", () => setData((d) => (d && d.status === "queued" ? { ...d, status: "running" } : d)));
    source.addEventListener("audit_done", (e) => {
      const data = parse(e as MessageEvent);
      setSummary(data);
      setCurrent(null);
      setLog((lines) => [...lines, { id: data.id, time: data.time, level: data.level, message: data.message }]);
      scheduleReload();
    });
    source.addEventListener("end", () => source.close());
    return () => {
      source.close();
      window.clearTimeout(reloadTimer.current);
    };
  }, [id, reload, setData]);

  if (detail.error) return <Banner kind="error">{detail.error.message}</Banner>;
  const audit = detail.data;
  if (!audit) return <Spinner />;

  const active = audit.status === "running" || audit.status === "queued";
  const anyScored = audit.sites.some((s) => s.state === "ok");
  const position = Math.min(audit.total, current?.position ?? audit.done_count + (active ? 1 : 0));

  async function stop() {
    setStopping(true);
    try {
      await api(`/api/audits/${id}/stop`, { method: "POST" });
      toast("Stopping – websites in progress will finish, the rest are skipped");
      void reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not stop the audit", "error");
    } finally {
      setStopping(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow={audit.project ?? "Audit"}
        title={`Audit #${audit.id}`}
        sub={`${plural(audit.total, "website")} · ${AUDIT_STATUS_LABEL[audit.status]}`}
        actions={
          active ? (
            <Button icon={Square} onClick={stop} loading={stopping} disabled={audit.cancel_requested}>
              {audit.cancel_requested ? "Stopping…" : "Stop"}
            </Button>
          ) : (
            <>
              {anyScored && (
                <a
                  className="btn"
                  href={`/api/audits/${audit.id}/claude-export`}
                  download
                  title="ZIP with every scored website: problems with exact locations, fixes, page contents, HTML and screenshots"
                >
                  <SquareTerminal size={16} aria-hidden /> Export for Claude Code
                </a>
              )}
              <Link to="/" className="btn">
                <LayoutDashboard size={16} aria-hidden /> Open dashboard
              </Link>
              <Link to="/audits/new" className="btn btn-primary">
                <Plus size={16} aria-hidden /> New audit
              </Link>
            </>
          )
        }
      />

      <Card title="Progress">
        <div className="stack">
          <div className="run-head">
            <span className="run-count num" aria-live="polite">
              {active ? `Web ${Math.max(position, 1)} of ${audit.total}` : `${audit.done_count} of ${audit.total} done`}
            </span>
            <span className="muted num">{audit.error_count ? `${plural(audit.error_count, "website")} not scored` : ""}</span>
          </div>
          <ProgressBar value={audit.done_count} max={audit.total} label="Audit progress" />
          <div className="run-current">
            {active && current ? (
              <>
                <strong>{current.url}</strong>: {current.step}
              </>
            ) : active ? (
              <span className="muted">{audit.status === "queued" ? "Waiting for a free worker…" : "Starting…"}</span>
            ) : null}
          </div>
          {summary && !active && (
            <Banner kind={summary.status === "done" ? "success" : summary.status === "failed" ? "error" : "warn"}>
              <strong>{summary.status === "done" ? "Audit finished." : summary.status === "failed" ? "Audit failed." : "Audit stopped."}</strong>{" "}
              {plural(summary.total, "website")} · {summary.scored} scored
              {summary.average !== null ? ` (average ${summary.average}/100)` : ""} · {plural(summary.errors, "website")} not scored ·{" "}
              {formatDuration(summary.duration_s)}
            </Banner>
          )}
        </div>
      </Card>

      <div className="grid-run">
        <Card title="Websites" meta="click a row for details">
          <SitesTable auditId={audit.id} sites={audit.sites} />
        </Card>
        <Card title="Live log" meta={log.length ? `${log.length} entries` : undefined}>
          <LiveLog lines={log} />
        </Card>
      </div>
    </>
  );
}

function LiveLog({ lines }: { lines: LogLine[] }) {
  const box = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const el = box.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 80) el.scrollTop = el.scrollHeight;
  }, [lines.length]);
  if (!lines.length) return <p className="muted">Messages appear here while the websites are checked.</p>;
  return (
    <ol className="log" ref={box} aria-label="Audit log">
      {lines.map((line) => {
        const Icon = LEVEL_ICON[line.level] ?? Info;
        return (
          <li key={line.id}>
            <time dateTime={line.time}>{formatTime(line.time)}</time>
            <Icon size={16} className={`lvl-${line.level}`} aria-label={LEVEL_LABEL[line.level]} />
            <span>
              {line.url && <span className="site">{line.url}: </span>}
              {line.message}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function SitesTable({ auditId, sites }: { auditId: number; sites: Site[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="table-box">
      <table className="table" style={{ minWidth: 560 }}>
        <thead>
          <tr>
            <th>Website</th>
            <th>Status</th>
            <th>Score</th>
            <th>Biggest problem</th>
          </tr>
        </thead>
        <tbody>
          {sites.map((site) => (
            <Fragment key={site.id}>
              <tr className="clickable" onClick={() => setOpen(open === site.id ? null : site.id)}>
                <td>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    style={{ padding: 0, minHeight: 0, gap: 6 }}
                    aria-expanded={open === site.id}
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpen(open === site.id ? null : site.id);
                    }}
                  >
                    {open === site.id ? <ChevronDown size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}
                    <span className="cell-main">{hostOf(site.final_url ?? site.input_url)}</span>
                  </button>
                  {site.company_name && <span className="cell-sub">{site.company_name}</span>}
                </td>
                <td>
                  <Tag color={STATE_COLOR[site.state]}>{site.state === "running" && site.step ? site.step : SITE_STATE_LABEL[site.state]}</Tag>
                </td>
                <td>
                  <ScoreBadge score={site.score} category={site.category} />
                </td>
                <td>{site.top_issue ?? (site.state_reason ? <span className="muted">{site.state_reason}</span> : <span className="muted">—</span>)}</td>
              </tr>
              {open === site.id && (
                <tr className="detail-row">
                  <td colSpan={4}>
                    <SiteDetail auditId={auditId} site={site} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type SiteDetailData = {
  issues: { check_id: string; status: "warn" | "fail"; impact: number; label: string; summary: string }[];
  result: { screenshots?: Record<string, string>; tech?: { cms: string | null; cms_version: string | null } } | null;
};

function claudePrompt(site: Site): string {
  return (
    `I unzipped a Web Audit export for ${hostOf(site.final_url ?? site.input_url)} into this project. ` +
    "Read the CLAUDE.md in that folder first, then help me fix the problems from its REPORT.md, biggest impact first. " +
    "Before each change, tell me what you will change and why; after it, show me how you verified it."
  );
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Clipboard API needs a secure context; fall back to a temporary textarea.
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

function ClaudeExport({ auditId, site }: { auditId: number; site: Site }) {
  const toast = useToast();
  return (
    <div className="export-box">
      <SquareTerminal size={20} aria-hidden className="export-icon" />
      <div className="export-text">
        <strong>Fix it with Claude Code</strong>
        <span className="muted">
          A ZIP with every problem and its exact place on the page, how to fix and verify it, the page contents, its HTML and screenshots. Unzip it
          into the website's project and paste the prompt into Claude Code.
        </span>
      </div>
      <div className="row" style={{ gap: 8 }}>
        <a className="btn btn-primary btn-sm" href={`/api/audits/${auditId}/sites/${site.id}/claude-export`} download>
          Download ZIP
        </a>
        <Button
          size="sm"
          icon={ClipboardCopy}
          onClick={async () => {
            const copied = await copyText(claudePrompt(site));
            toast(copied ? "Prompt copied – paste it into Claude Code" : "Could not copy the prompt", copied ? "ok" : "error");
          }}
        >
          Copy prompt
        </Button>
      </div>
    </div>
  );
}

function SiteDetail({ auditId, site }: { auditId: number; site: Site }) {
  const data = useApi<SiteDetailData>(site.state === "ok" ? `/api/audits/${auditId}/sites/${site.id}` : null);
  if (site.state !== "ok") return <p className="muted">{site.state_reason ?? SITE_STATE_LABEL[site.state]}</p>;
  if (!data.data) return <Spinner />;
  const shots = Object.keys(data.data.result?.screenshots ?? {});
  const tech = data.data.result?.tech;
  return (
    <div className="stack">
      <ClaudeExport auditId={auditId} site={site} />
      {data.data.issues.length ? (
        <ul className="issue-list" aria-label="Problems, biggest impact first">
          {data.data.issues.slice(0, 10).map((issue) => (
            <li key={issue.check_id}>
              {issue.status === "fail" ? <CircleAlert size={16} className="lvl-error" style={{ color: "var(--danger)" }} aria-label="Problem" /> : <TriangleAlert size={16} style={{ color: "var(--warning)" }} aria-label="Warning" />}
              <span>
                <span className="cell-main">{issue.label}</span>
                <span className="cell-sub">{issue.summary}</span>
              </span>
              <span className="muted num" title="Points of the total score this costs">
                −{issue.impact.toFixed(1)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p>No problems found.</p>
      )}
      {tech?.cms && <span className="pill">{[tech.cms, tech.cms_version].filter(Boolean).join(" ")}</span>}
      {shots.length > 0 && (
        <div className="shots">
          {shots.map((name) => (
            <a key={name} href={`/api/audits/${auditId}/sites/${site.id}/screenshots/${name}`} target="_blank" rel="noreferrer">
              <img
                src={`/api/audits/${auditId}/sites/${site.id}/screenshots/${name}`}
                alt={`${name} screenshot of ${hostOf(site.final_url)}`}
                width={name === "mobile" ? 90 : 280}
                loading="lazy"
              />
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
