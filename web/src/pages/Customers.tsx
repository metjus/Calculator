import { BellRing, Plus, Search, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Bars, Donut, Legend } from "../components/charts";
import { Banner, Button, Card, EmptyState, Field, PageHeader, Spinner, Tag, TextInput } from "../components/ui";
import { api, type CrmStatus, type CustomerCard, type CustomerList } from "../lib/api";
import { formatDate } from "../lib/format";
import { useToast } from "../lib/toast";
import { useApi } from "../lib/useApi";

/** Status colours differ in lightness as well as hue, as the brief asks. */
export const STATUS_COLOUR: Record<CrmStatus, string> = {
  lead: "var(--neutral)",
  audited: "var(--r5)",
  contacted: "var(--r4)",
  waiting: "var(--ok)",
  interested: "var(--r3)",
  proposal: "var(--r2)",
  deal: "var(--good)",
  not_interested: "var(--crit)",
  no_answer: "var(--weak)",
};

export function customerName(row: { name: string | null; domain: string | null }): string {
  return row.name ?? row.domain ?? "Unnamed business";
}

export function Customers() {
  const list = useApi<CustomerList>("/api/companies");
  const toast = useToast();
  const [status, setStatus] = useState<CrmStatus | "">("");
  const [project, setProject] = useState("");
  const [website, setWebsite] = useState<"" | "yes" | "no">("");
  const [text, setText] = useState("");
  const [adding, setAdding] = useState(false);

  const data = list.data;
  const rows = useMemo(() => {
    const needle = text.trim().toLowerCase();
    return (data?.rows ?? []).filter(
      (row) =>
        (!status || row.status === status) &&
        (!project || row.project === project) &&
        (!website || (website === "yes") === row.has_website) &&
        (!needle || [row.name, row.domain, row.project].some((value) => value?.toLowerCase().includes(needle))),
    );
  }, [data, status, project, website, text]);

  if (list.error) return <Banner kind="error">{list.error.message}</Banner>;
  if (!data) return list.loading ? <Spinner /> : null;

  const stats = data.stats;
  const slices = stats.by_status.map((row) => ({ label: row.label, value: row.count, color: STATUS_COLOUR[row.status] }));

  return (
    <>
      <PageHeader
        eyebrow="My workspace"
        title="Customers"
        sub={`${stats.total} in total · ${stats.open} still open · ${data.follow_ups.length} need a nudge`}
        actions={
          <Button variant="primary" icon={Plus} onClick={() => setAdding(true)}>
            Add customer
          </Button>
        }
      />

      {adding && <AddCustomer onDone={(message) => { setAdding(false); if (message) { toast(message); void list.reload(); } }} />}

      {data.follow_ups.length > 0 && (
        <Card title="Follow up" meta={`${data.follow_ups.length} waiting on you`} id="followups">
          <ul className="follow-list">
            {data.follow_ups.slice(0, 8).map((row) => (
              <li key={row.id}>
                <BellRing size={15} aria-hidden className="lvl-warn" />
                <Link to={`/customers/${row.id}`} className="cell-main">
                  {customerName(row)}
                </Link>
                <span className="cell-sub">
                  {row.reason === "next_step"
                    ? `${row.next_step || "Next step"} · due ${formatDate(row.next_step_at)}`
                    : `Waiting for an answer since ${formatDate(row.status_at)}`}
                </span>
                <Tag color={STATUS_COLOUR[row.status]}>{row.status_label}</Tag>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid-crm">
        <Card title="Funnel" meta="where everyone stands">
          <Bars
            bars={stats.funnel.map((row) => ({ key: row.status, label: row.label, value: row.count }))}
            max={Math.max(1, ...stats.funnel.map((row) => row.count))}
            selected={status || null}
            onPick={(key) => setStatus((current) => (current === key ? "" : (key as CrmStatus)))}
          />
        </Card>
        <Card title="Result" meta="of everyone contacted">
          <div className="kpis">
            <Kpi label="Contacted" value={stats.conversion.contacted} />
            <Kpi label="Interested" value={stats.conversion.interested} sub={pct(stats.conversion.interested_pct)} />
            <Kpi label="Deals" value={stats.conversion.deals} sub={pct(stats.conversion.deal_pct)} />
            <Kpi label="Agreed" value={stats.deal_value ? `${stats.deal_value} €` : "—"} />
            <Kpi label="Answer takes" value={stats.answer_days === null ? "—" : `${stats.answer_days} d`} />
          </div>
          <Weeks weeks={stats.weeks} />
        </Card>
        <Card title="By status" meta={`${stats.total} customers`}>
          {slices.length === 0 ? (
            <p className="muted">No customers yet.</p>
          ) : (
            <>
              <Donut slices={slices} center={<strong className="num">{stats.total}</strong>} label="Customers by status" />
              <Legend slices={slices} />
            </>
          )}
        </Card>
      </div>

      <Card
        title="All customers"
        meta={`${rows.length} shown`}
        id="list"
      >
        <div className="filters">
          <div className="search">
            <Search size={16} aria-hidden />
            <TextInput value={text} onChange={(e) => setText(e.target.value)} placeholder="Search name, domain or project" aria-label="Search customers" />
          </div>
          <select className="select" value={status} onChange={(e) => setStatus(e.target.value as CrmStatus | "")} aria-label="Status">
            <option value="">Every status</option>
            {data.statuses.map((row) => (
              <option key={row.id} value={row.id}>
                {row.label}
              </option>
            ))}
          </select>
          <select className="select" value={project} onChange={(e) => setProject(e.target.value)} aria-label="Project">
            <option value="">Every project</option>
            {data.projects.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <select className="select" value={website} onChange={(e) => setWebsite(e.target.value as "" | "yes" | "no")} aria-label="Website">
            <option value="">With and without a website</option>
            <option value="yes">Has a website</option>
            <option value="no">No website (lead)</option>
          </select>
        </div>

        {rows.length === 0 ? (
          <EmptyState icon={Users} title="Nobody here">Run an audit, search for businesses, or add a customer by hand.</EmptyState>
        ) : (
          <div className="table-box">
            <table className="table" style={{ minWidth: 820 }}>
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Status</th>
                  <th>Score</th>
                  <th>Next step</th>
                  <th>Last contact</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <Link to={`/customers/${row.id}`} className="cell-main">
                        {customerName(row)}
                      </Link>
                      <span className="cell-sub">
                        {row.has_website ? row.domain : "No website"}
                        {row.project ? ` · ${row.project}` : ""}
                        {row.do_not_contact ? " · do not contact" : ""}
                      </span>
                    </td>
                    <td>
                      <Tag color={STATUS_COLOUR[row.status]}>{row.status_label}</Tag>
                    </td>
                    <td className="num">{row.score ?? "—"}</td>
                    <td>
                      {row.next_step ? (
                        <>
                          <span className="cell-main">{row.next_step}</span>
                          <span className="cell-sub">{formatDate(row.next_step_at)}</span>
                        </>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="muted">{row.last_contact ? formatDate(row.last_contact) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

function pct(value: number | null): string | undefined {
  return value === null ? undefined : `${value}%`;
}

function Kpi({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="kpi">
      <span className="kpi-label">{label}</span>
      <span className="kpi-value num">{value}</span>
      {sub && <span className="kpi-sub">{sub}</span>}
    </div>
  );
}

/** Outreach and deals week by week — the brief's line chart, drawn as two thin bars per week. */
function Weeks({ weeks }: { weeks: { week: string; contacted: number; deals: number }[] }) {
  if (weeks.length === 0) return <p className="muted">Contacts and deals appear here once you start logging them.</p>;
  const max = Math.max(1, ...weeks.map((w) => Math.max(w.contacted, w.deals)));
  return (
    <div className="weeks" role="img" aria-label="Contacts and deals by week">
      {weeks.map((week) => (
        <div key={week.week} className="week" title={`${formatDate(week.week)}: ${week.contacted} contacted, ${week.deals} deals`}>
          <span className="stack-bars">
            <i style={{ height: `${(week.contacted / max) * 100}%`, background: "var(--r3)" }} />
            <i style={{ height: `${(week.deals / max) * 100}%`, background: "var(--good)" }} />
          </span>
          <span className="week-label">{formatDate(week.week).slice(0, 5)}</span>
        </div>
      ))}
    </div>
  );
}

function AddCustomer({ onDone }: { onDone: (message?: string) => void }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [project, setProject] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const card = await api<CustomerCard>("/api/companies", { method: "POST", body: { name, url, project } });
      onDone(`${customerName(card.customer)} added`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add the customer");
      setBusy(false);
    }
  }

  return (
    <Card title="Add a customer" meta="a business without a website is a lead for a new one">
      {error && <Banner kind="error">{error}</Banner>}
      <div className="add-row">
        <Field label="Business name">
          {(id, describedBy) => <TextInput id={id} aria-describedby={describedBy} value={name} onChange={(e) => setName(e.target.value)} maxLength={300} />}
        </Field>
        <Field label="Website" hint="Leave empty for a business that has none yet.">
          {(id, describedBy) => <TextInput id={id} aria-describedby={describedBy} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="example.sk" />}
        </Field>
        <Field label="Project">
          {(id, describedBy) => <TextInput id={id} aria-describedby={describedBy} value={project} onChange={(e) => setProject(e.target.value)} maxLength={200} />}
        </Field>
      </div>
      <div className="row" style={{ gap: 8, marginTop: 12 }}>
        <Button variant="primary" loading={busy} onClick={save}>
          Add
        </Button>
        <Button onClick={() => onDone()}>Cancel</Button>
      </div>
    </Card>
  );
}
