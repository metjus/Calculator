import { ClipboardCheck, Plus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { Banner, Card, EmptyState, PageHeader, ProgressBar, Spinner, Tag } from "../components/ui";
import type { Audit } from "../lib/api";
import { AUDIT_STATUS_LABEL, formatDate } from "../lib/format";
import { useApi } from "../lib/useApi";

const STATUS_COLOR: Record<Audit["status"], string> = {
  queued: "var(--neutral)",
  running: "var(--accent)",
  done: "var(--good)",
  cancelled: "var(--weak)",
  failed: "var(--crit)",
};

export function AuditTable({ audits }: { audits: Audit[] }) {
  const navigate = useNavigate();
  return (
    <div className="table-box">
      <table className="table">
        <thead>
          <tr>
            <th>Audit</th>
            <th>Project</th>
            <th>Status</th>
            <th>Progress</th>
            <th>Started</th>
          </tr>
        </thead>
        <tbody>
          {audits.map((a) => (
            <tr key={a.id} className="clickable" onClick={() => navigate(`/audits/${a.id}`)}>
              <td>
                <Link to={`/audits/${a.id}`} className="cell-main" onClick={(e) => e.stopPropagation()}>
                  Audit #{a.id}
                </Link>
                <span className="cell-sub">
                  {a.total} {a.total === 1 ? "website" : "websites"}
                </span>
              </td>
              <td>{a.project ?? <span className="muted">—</span>}</td>
              <td>
                <Tag color={STATUS_COLOR[a.status]}>{AUDIT_STATUS_LABEL[a.status]}</Tag>
              </td>
              <td style={{ minWidth: 160 }}>
                <ProgressBar value={a.done_count} max={a.total} label={`Audit ${a.id} progress`} />
                <span className="cell-sub num">
                  {a.done_count} of {a.total}
                  {a.error_count ? ` · ${a.error_count} not scored` : ""}
                </span>
              </td>
              <td className="num">{formatDate(a.started_at ?? a.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Audits() {
  const audits = useApi<Audit[]>("/api/audits");
  return (
    <>
      <PageHeader
        eyebrow="Batch audits"
        title="Audits"
        actions={
          <Link to="/audits/new" className="btn btn-primary">
            <Plus size={16} aria-hidden /> New audit
          </Link>
        }
      />
      {audits.error && <Banner kind="error">{audits.error.message}</Banner>}
      {audits.loading && !audits.data ? (
        <Spinner />
      ) : audits.data?.length ? (
        <Card>
          <AuditTable audits={audits.data} />
        </Card>
      ) : (
        <EmptyState
          icon={ClipboardCheck}
          title="No audits yet – start the first one"
          action={
            <Link to="/audits/new" className="btn btn-primary">
              <Plus size={16} aria-hidden /> New audit
            </Link>
          }
        >
          An audit checks a list of websites in the background. You can close the page; progress and results stay here.
        </EmptyState>
      )}
    </>
  );
}
