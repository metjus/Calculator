import { Ban, ChevronRight, CircleAlert, ClipboardCheck, ExternalLink, Plus, RotateCw, Search as SearchIcon, ShieldAlert, Undo2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bars, Donut, Legend, type Slice } from "../components/charts";
import { Banner, Button, Card, EmptyState, PageHeader, ScoreBadge, Select, Spinner, Tag, TextInput } from "../components/ui";
import { api, type Category, type CreateResult, type DashboardData, type ManualDecision, type ManualSite } from "../lib/api";
import { CATEGORY_LABEL, CATEGORY_VAR, formatDay, plural } from "../lib/format";
import { useToast } from "../lib/toast";
import { useApi } from "../lib/useApi";

const PERIODS = [
  { value: "", label: "Any time" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "365", label: "Last 12 months" },
];
const CMS_RAMP = ["var(--r1)", "var(--r2)", "var(--r3)", "var(--r4)", "var(--r5)"];
const PAGE = 50;

export const DECISION_LABEL: Record<ManualDecision, string> = { contact: "Worth contacting", skip: "Skipped" };

/** Start a new audit of one website (from the dashboard or the detail page). */
export async function auditAgain(url: string, project: string | null): Promise<number | null> {
  const created = await api<CreateResult>("/api/audits", { body: { project, urls: url } });
  return created.audit?.id ?? null;
}

export function Dashboard() {
  const [project, setProject] = useState("");
  const [days, setDays] = useState("");
  const query = new URLSearchParams({ ...(project && { project }), ...(days && { days }) }).toString();
  const dash = useApi<DashboardData>(`/api/dashboard${query ? `?${query}` : ""}`);
  const filtered = Boolean(project || days);
  const data = dash.data;

  return (
    <>
      <PageHeader
        eyebrow="Overview"
        title="Dashboard"
        actions={
          <>
            <Select aria-label="Project" value={project} onChange={(e) => setProject(e.target.value)}>
              <option value="">All projects</option>
              {data?.projects.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </Select>
            <Select aria-label="Audited" value={days} onChange={(e) => setDays(e.target.value)}>
              {PERIODS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </Select>
            <Link to="/audits/new" className="btn btn-primary">
              <Plus size={16} aria-hidden /> New audit
            </Link>
          </>
        }
      />
      {dash.error && <Banner kind="error">{dash.error.message}</Banner>}
      {!data ? (
        <Spinner />
      ) : !data.websites.length && !data.manual.length ? (
        filtered ? (
          <EmptyState icon={ClipboardCheck} title="No websites match these filters">
            Choose another project or a longer period.
          </EmptyState>
        ) : (
          <EmptyState
            icon={ClipboardCheck}
            title="No audits yet – start the first one"
            action={
              <div className="row">
                <Link to="/audits/new" className="btn btn-primary">
                  <Plus size={16} aria-hidden /> New audit
                </Link>
                <Link to="/search" className="btn">
                  <SearchIcon size={16} aria-hidden /> Find businesses
                </Link>
              </div>
            }
          >
            Paste a few website addresses or upload a CSV. Each site gets a score from 0 to 100 and a list of problems in plain language. Or find
            businesses by category and area first.
          </EmptyState>
        )
      ) : (
        <Overview data={data} reload={dash.reload} />
      )}
    </>
  );
}

function Overview({ data, reload }: { data: DashboardData; reload: () => Promise<void> }) {
  const [problem, setProblem] = useState<string | null>(null);
  const m = data.metrics;
  const categories: Slice[] = (Object.keys(CATEGORY_LABEL) as Category[]).map((c) => ({ label: CATEGORY_LABEL[c], value: data.categories[c], color: CATEGORY_VAR[c] }));
  const binary = (v: { yes: number; no: number }): Slice[] => [
    { label: "No", value: v.no, color: "var(--crit)" },
    { label: "Yes", value: v.yes, color: "var(--neutral)" },
  ];
  const cms: Slice[] = data.cms.map((c, i) => ({ label: c.name, value: c.count, color: c.name === "Other" ? "var(--other)" : CMS_RAMP[i] ?? "var(--other)" }));
  // The centre names the most common real system; "Not detected" and "Other" are not systems.
  const topCms = data.cms.find((c) => c.name !== "Not detected" && c.name !== "Other");
  const cmsTotal = data.cms.reduce((sum, c) => sum + c.count, 0);
  const problemLabel = data.problems.find((p) => p.check_id === problem)?.label;

  return (
    <>
      <div className="strip">
        <div className="stat">
          <div className="stat-label">Audited websites</div>
          <div className="stat-value">{m.audited}</div>
          <div className="stat-note">{m.to_check ? `+${m.to_check} to check manually` : "all scored"}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Average score</div>
          <div className="stat-value">{m.average ?? "—"}</div>
          <div className="stat-note">out of 100</div>
        </div>
        <div className="stat">
          <div className="stat-label">Critical</div>
          <div className="stat-value">{m.critical}</div>
          <div className="stat-note">score below 40</div>
        </div>
        <div className="stat">
          <div className="stat-label">Without HTTPS</div>
          <div className="stat-value">{m.without_https}</div>
          <div className="stat-note">{m.audited ? `${Math.round((m.without_https / m.audited) * 100)} % of audited` : "—"}</div>
        </div>
      </div>

      <div className="grid-2">
        <Card title="Score categories" meta={plural(m.audited, "website")}>
          <div className="donut-row">
            <Donut slices={categories} label="Score categories" center={<><b>{m.average ?? "—"}</b><span>average score</span></>} />
            <Legend slices={categories} percent />
          </div>
        </Card>
        <Card title="Most common problems" meta={data.problems.length ? "click one to filter the table" : undefined}>
          {data.problems.length ? (
            <Bars
              bars={data.problems.map((p) => ({ key: p.check_id, label: p.label, value: p.count }))}
              max={m.audited}
              selected={problem}
              onPick={(key) => setProblem((current) => (current === key ? null : key))}
            />
          ) : (
            <p className="muted">No problems found on the scored websites.</p>
          )}
        </Card>
      </div>

      <div className="grid-4">
        <Card title="HTTPS">
          <div className="donut-row">
            <Donut size="sm" slices={binary(data.https)} label="HTTPS" center={<><b>{data.https.no}</b><span>without</span></>} />
            <Legend slices={binary(data.https)} />
          </div>
        </Card>
        <Card title="Mobile-friendly">
          <div className="donut-row">
            <Donut size="sm" slices={binary(data.mobile)} label="Mobile-friendly" center={<><b>{data.mobile.no}</b><span>not friendly</span></>} />
            <Legend slices={binary(data.mobile)} />
          </div>
        </Card>
        <Card title="CMS">
          <div className="donut-row">
            <Donut
              size="sm"
              slices={cms}
              label="CMS"
              center={topCms ? <><b>{Math.round((topCms.count / cmsTotal) * 100)} %</b><span>{topCms.name}</span></> : <><b>—</b><span>none found</span></>}
            />
            <Legend slices={cms} />
          </div>
        </Card>
        <CheckManually items={data.manual} reload={reload} />
      </div>

      <WebsitesTable data={data} problem={problem} problemLabel={problemLabel ?? null} clearProblem={() => setProblem(null)} />
    </>
  );
}

const STATE_ICON = { protected: ShieldAlert, disallowed: Ban } as const;

function CheckManually({ items, reload }: { items: ManualSite[]; reload: () => Promise<void> }) {
  const toast = useToast();
  const navigate = useNavigate();
  const [showChecked, setShowChecked] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const open = items.filter((i) => !i.decision);
  const checked = items.filter((i) => i.decision);

  async function decide(item: ManualSite, decision: ManualDecision | null) {
    if (!item.company_id) return;
    setBusy(item.site_id);
    try {
      await api(`/api/companies/${item.company_id}/manual-check`, { method: "PUT", body: { decision } });
      toast(decision ? `${item.domain}: ${DECISION_LABEL[decision].toLowerCase()}` : `${item.domain} is back on the list`);
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save", "error");
    } finally {
      setBusy(null);
    }
  }

  async function again(item: ManualSite) {
    setBusy(item.site_id);
    try {
      const id = await auditAgain(item.url, item.project);
      if (id) navigate(`/audits/${id}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not start the audit", "error");
      setBusy(null);
    }
  }

  const list = showChecked ? checked : open;
  return (
    <Card title="Check manually" meta="not scored">
      {!list.length ? (
        <p className="muted">{showChecked ? "Nothing checked yet." : "Nothing to check – every website was scored or already checked."}</p>
      ) : (
        <ul className="manual">
          {list.map((item) => {
            const Icon = STATE_ICON[item.state as keyof typeof STATE_ICON] ?? CircleAlert;
            return (
              <li key={item.site_id}>
                <Icon size={18} className="manual-icon" aria-hidden />
                <div className="manual-body">
                  <a href={item.url} target="_blank" rel="noreferrer noopener" className="manual-domain">
                    {item.domain} <ExternalLink size={13} aria-hidden />
                  </a>
                  <span className="manual-reason">{item.reason ?? "Not scored"}</span>
                  {item.decision ? (
                    <div className="manual-actions">
                      <Tag color={item.decision === "contact" ? "var(--accent)" : "var(--neutral)"}>{DECISION_LABEL[item.decision]}</Tag>
                      <Button size="sm" variant="ghost" icon={Undo2} loading={busy === item.site_id} onClick={() => void decide(item, null)}>
                        Undo
                      </Button>
                    </div>
                  ) : (
                    <div className="manual-actions">
                      {item.company_id && (
                        <>
                          <Button size="sm" disabled={busy === item.site_id} onClick={() => void decide(item, "contact")}>
                            Worth contacting
                          </Button>
                          <Button size="sm" variant="ghost" disabled={busy === item.site_id} onClick={() => void decide(item, "skip")}>
                            Skip
                          </Button>
                        </>
                      )}
                      <Button size="sm" variant="ghost" icon={RotateCw} loading={busy === item.site_id} aria-label={`Audit ${item.domain} again`} title="Audit again" onClick={() => void again(item)} />
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {(checked.length > 0 || showChecked) && (
        <button type="button" className="link-btn manual-toggle" onClick={() => setShowChecked((v) => !v)}>
          {showChecked ? `Back to ${plural(open.length, "website")} to check` : `${checked.length} checked by hand – show`}
        </button>
      )}
    </Card>
  );
}

function WebsitesTable({ data, problem, problemLabel, clearProblem }: { data: DashboardData; problem: string | null; problemLabel: string | null; clearProblem: () => void }) {
  const [text, setText] = useState("");
  const [category, setCategory] = useState<Category | "">("");
  const [limit, setLimit] = useState(PAGE);
  const rows = useMemo(() => {
    const needle = text.trim().toLowerCase();
    return data.websites.filter(
      (w) =>
        (!needle || w.domain.includes(needle) || (w.company ?? "").toLowerCase().includes(needle)) &&
        (!category || w.category === category) &&
        (!problem || w.issue_ids.includes(problem)),
    );
  }, [data.websites, text, category, problem]);

  return (
    <Card title="Websites" meta="worst score first · click a website for details">
      <div className="filters">
        <div className="search-box">
          <SearchIcon size={16} aria-hidden />
          <TextInput type="search" aria-label="Search websites" placeholder="Search company or domain" value={text} onChange={(e) => setText(e.target.value)} />
        </div>
        <Select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value as Category | "")}>
          <option value="">All categories</option>
          {(Object.keys(CATEGORY_LABEL) as Category[]).map((c) => (
            <option key={c} value={c}>
              {CATEGORY_LABEL[c]}
            </option>
          ))}
        </Select>
        {problem && (
          <span className="chip">
            Problem: {problemLabel}
            <button type="button" onClick={clearProblem} aria-label="Remove the problem filter">
              <X size={16} aria-hidden />
            </button>
          </span>
        )}
      </div>
      {rows.length ? (
        <div className="table-box">
          <table className="table" style={{ minWidth: 860 }}>
            <thead>
              <tr>
                <th>Website</th>
                <th>Project</th>
                <th aria-sort="ascending">Score</th>
                <th>Biggest problem</th>
                <th>Problems</th>
                <th>Audited</th>
                <th>
                  <span className="sr-only">Open</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, limit).map((w) => {
                const to = `/audits/${w.audit_id}/sites/${w.site_id}`;
                return (
                  <tr key={w.site_id}>
                    <td>
                      <Link to={to} className="cell-link">
                        {w.domain}
                      </Link>
                      {w.company && <span className="cell-sub">{w.company}</span>}
                    </td>
                    <td>{w.project ?? <span className="muted">—</span>}</td>
                    <td>
                      <ScoreBadge score={w.score} category={w.category} />
                    </td>
                    <td>{w.top_issue ?? <span className="muted">—</span>}</td>
                    <td className="num">{w.issues}</td>
                    <td className="num nowrap">{formatDay(w.finished_at)}</td>
                    <td>
                      <Link to={to} className="btn btn-ghost btn-sm btn-icon" aria-label={`Open ${w.domain}`}>
                        <ChevronRight size={16} aria-hidden />
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">No websites match these filters.</p>
      )}
      <div className="table-foot">
        <span>
          {rows.length === data.websites.length ? plural(rows.length, "website") : `${rows.length} of ${plural(data.websites.length, "website")}`}
          {rows.length > limit ? ` · showing the first ${limit}` : ""}
        </span>
        {rows.length > limit && (
          <Button size="sm" onClick={() => setLimit((n) => n + PAGE * 4)}>
            Show more
          </Button>
        )}
      </div>
    </Card>
  );
}
