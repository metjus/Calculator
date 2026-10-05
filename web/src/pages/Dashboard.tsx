import { ClipboardCheck, Plus, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { AuditTable } from "./Audits";
import { Banner, Card, EmptyState, PageHeader, Spinner } from "../components/ui";
import type { Audit, Company } from "../lib/api";
import { useApi } from "../lib/useApi";

export function Dashboard() {
  const audits = useApi<Audit[]>("/api/audits");
  const summary = useApi<{ audits: number; scored_sites: number }>("/api/audits/stats/summary");
  const companies = useApi<Company[]>("/api/companies");
  const noWebsite = companies.data?.filter((c) => !c.has_website).length ?? 0;
  const running = audits.data?.filter((a) => a.status === "running" || a.status === "queued") ?? [];

  return (
    <>
      <PageHeader
        eyebrow="Overview"
        title="Dashboard"
        actions={
          <Link to="/audits/new" className="btn btn-primary">
            <Plus size={16} aria-hidden /> New audit
          </Link>
        }
      />
      {audits.error && <Banner kind="error">{audits.error.message}</Banner>}
      {audits.loading && !audits.data ? (
        <Spinner />
      ) : audits.data && audits.data.length === 0 ? (
        <EmptyState
          icon={ClipboardCheck}
          title="No audits yet – start the first one"
          action={
            <div className="row">
              <Link to="/audits/new" className="btn btn-primary">
                <Plus size={16} aria-hidden /> New audit
              </Link>
              <Link to="/search" className="btn">
                <Search size={16} aria-hidden /> Find businesses
              </Link>
            </div>
          }
        >
          Paste a few website addresses or upload a CSV. Each site gets a score from 0 to 100 and a list of problems in plain language. Or find businesses by
          category and area first.
        </EmptyState>
      ) : (
        <>
          <div className="strip">
            <div className="stat">
              <div className="stat-label">Audits</div>
              <div className="stat-value">{summary.data?.audits ?? "—"}</div>
              <div className="stat-note">{running.length ? `${running.length} in progress` : "none running"}</div>
            </div>
            <div className="stat">
              <div className="stat-label">Scored websites</div>
              <div className="stat-value">{summary.data?.scored_sites ?? "—"}</div>
              <div className="stat-note">across all audits</div>
            </div>
            <div className="stat">
              <div className="stat-label">Businesses</div>
              <div className="stat-value">{companies.data?.length ?? "—"}</div>
              <div className="stat-note">in your list</div>
            </div>
            <div className="stat">
              <div className="stat-label">Without a website</div>
              <div className="stat-value">{noWebsite}</div>
              <div className="stat-note">leads for a new website</div>
            </div>
          </div>
          <Banner>Charts, problem statistics and the worst-first table arrive with the audit dashboard in the next stage.</Banner>
          <Card title="Recent audits" meta={<Link to="/audits">All audits</Link>}>
            <AuditTable audits={(audits.data ?? []).slice(0, 6)} />
          </Card>
        </>
      )}
    </>
  );
}
