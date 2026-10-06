import { ChevronDown, ChevronRight, ChevronUp, ExternalLink, Eye, FileDown, RotateCw, SquareTerminal, Users } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { claudePrompt, copyText, exportUrl, Screenshots } from "../components/SiteParts";
import { Banner, Button, Card, PageHeader, ScoreBadge, Spinner, Tag } from "../components/ui";
import { api, type ManualDecision, type Problem, type SiteView } from "../lib/api";
import { CATEGORY_LABEL, CATEGORY_VAR, formatDate, hostOf, plural, SITE_STATE_LABEL } from "../lib/format";
import { useToast } from "../lib/toast";
import { useApi } from "../lib/useApi";
import { auditAgain, DECISION_LABEL } from "./Dashboard";

const TONE_COLOR = { bad: "var(--crit)", warn: "var(--weak)", ok: "var(--neutral)" };
const AREA_DOT: Record<string, string> = { mobile: "var(--crit)", trust: "var(--weak)", speed: "var(--ok)" };
const SHOWN = 8;
const R = 42;
const C = 2 * Math.PI * R;

export function SiteDetail() {
  const { auditId, siteId } = useParams();
  const view = useApi<SiteView>(`/api/audits/${auditId}/sites/${siteId}`);
  if (view.error) return <Banner kind="error">{view.error.message}</Banner>;
  if (!view.data) return <Spinner />;
  return <Detail data={view.data} reload={view.reload} />;
}

function Detail({ data, reload }: { data: SiteView; reload: () => Promise<void> }) {
  const toast = useToast();
  const navigate = useNavigate();
  const [starting, setStarting] = useState(false);
  const { site, audit } = data;
  const url = site.final_url ?? site.input_url;
  const host = hostOf(url);
  const scored = site.state === "ok" && site.score !== null && site.category !== null;

  async function again() {
    setStarting(true);
    try {
      const id = await auditAgain(url, audit.project);
      if (id) navigate(`/audits/${id}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not start the audit", "error");
      setStarting(false);
    }
  }

  async function exportForClaude() {
    window.location.href = exportUrl(audit.id, site.id);
    const copied = await copyText(claudePrompt(host));
    toast(copied ? "ZIP is downloading – prompt copied, paste it into Claude Code" : "ZIP is downloading", "ok");
  }

  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/">Dashboard</Link>
        <ChevronRight size={14} aria-hidden />
        <Link to={`/audits/${audit.id}`}>{audit.project ?? `Audit #${audit.id}`}</Link>
        <ChevronRight size={14} aria-hidden />
        <span aria-current="page">{host}</span>
      </nav>
      <PageHeader
        eyebrow="Website detail"
        title={host}
        sub={
          <span className="sub-parts">
            {data.company?.name && <span>{data.company.name}</span>}
            <span>Audited {formatDate(data.finished_at)}</span>
            <a href={url} target="_blank" rel="noreferrer noopener">
              {url}
            </a>
          </span>
        }
        actions={
          <>
            <a className="btn" href={url} target="_blank" rel="noreferrer noopener">
              <ExternalLink size={16} aria-hidden /> Open website
            </a>
            <Button icon={RotateCw} loading={starting} onClick={again}>
              Audit again
            </Button>
            {scored && (
              <Button icon={SquareTerminal} onClick={exportForClaude} title="ZIP with every problem, its exact place on the page and how to fix it; the prompt is copied too">
                Fix with Claude Code
              </Button>
            )}
            <Button variant="primary" icon={FileDown} disabled title="PDF reports for clients arrive in a later update">
              Create PDF
            </Button>
          </>
        }
      />
      {!scored ? <NotScored data={data} reload={reload} /> : <Scored data={data} />}
    </>
  );
}

function NotScored({ data, reload }: { data: SiteView; reload: () => Promise<void> }) {
  const toast = useToast();
  const decision = data.company?.manual_check ?? null;
  async function decide(value: ManualDecision | null) {
    if (!data.company) return;
    try {
      await api(`/api/companies/${data.company.id}/manual-check`, { method: "PUT", body: { decision: value } });
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save", "error");
    }
  }
  return (
    <Card title="Not scored">
      <div className="stack">
        <p>
          <strong>{SITE_STATE_LABEL[data.site.state]}.</strong> {data.site.state_reason}
        </p>
        <p className="muted">Open the website yourself and decide whether it is worth contacting. It stays out of every statistic.</p>
        {data.company &&
          (decision ? (
            <div className="row">
              <Tag color={decision === "contact" ? "var(--accent)" : "var(--neutral)"}>{DECISION_LABEL[decision]}</Tag>
              <Button size="sm" variant="ghost" onClick={() => void decide(null)}>
                Undo
              </Button>
            </div>
          ) : (
            <div className="row">
              <Button onClick={() => void decide("contact")}>Worth contacting</Button>
              <Button variant="ghost" onClick={() => void decide("skip")}>
                Skip
              </Button>
            </div>
          ))}
      </div>
    </Card>
  );
}

function Scored({ data }: { data: SiteView }) {
  const { site } = data;
  const score = site.score ?? 0;
  const category = site.category!;
  const shots = Object.keys(data.result?.screenshots ?? {});
  const cookie = data.result?.inventory?.cookie_banner;
  // The two areas that lose the most weighted points, and what the top three problems are worth.
  const costly = data.areas
    .filter((a) => a.score !== null && a.score < 100)
    .map((a) => ({ label: a.label, lost: a.weight * (100 - (a.score ?? 0)) }))
    .sort((a, b) => b.lost - a.lost)
    .slice(0, 2)
    .map((a) => a.label);
  const topThree = data.problems.slice(0, 3).reduce((sum, p) => sum + p.impact, 0);

  return (
    <>
      <div className="grid-2">
        <Card title="Score" meta="weighted by area">
          <div className="score-top">
            <div className="ring">
              <svg viewBox="0 0 100 100" role="img" aria-label={`Score ${score} of 100, ${CATEGORY_LABEL[category]}`}>
                <g transform="rotate(-90 50 50)">
                  <circle cx="50" cy="50" r={R} className="ring-track" />
                  <circle cx="50" cy="50" r={R} className="ring-fill" style={{ stroke: CATEGORY_VAR[category], strokeDasharray: `${(score / 100) * C} ${C}` }} />
                </g>
              </svg>
              <div className="ring-center">
                <b>{score}</b>
                <span>of 100</span>
              </div>
            </div>
            <div className="verdict">
              <span className="verdict-cat">
                <i style={{ background: CATEGORY_VAR[category] }} aria-hidden />
                {CATEGORY_LABEL[category]}
              </span>
              <p>
                {costly.length ? `${costly.join(" and ")} cost${costly.length === 1 ? "s" : ""} the most. ` : "No area loses points. "}
                {data.problems.length > 0 && `Fixing the top ${Math.min(3, data.problems.length)} problems is worth about ${Math.round(topThree)} points.`}
              </p>
            </div>
          </div>
          <div className="areas">
            {[...data.areas.filter((a) => a.score !== null), ...data.areas.filter((a) => a.score === null)].map((a) => (
              <div key={a.area} className={`area-row${a.score === null ? " off" : ""}`}>
                <span className="area-name">{a.label}</span>
                <span className="bar-track">
                  <span className="bar-fill" style={{ width: `${a.score ?? 0}%` }} />
                </span>
                <span className="area-score num">{a.score ?? "—"}</span>
                <span className="area-weight num">{a.score === null ? "not used" : `${a.weight} %`}</span>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Screenshots" meta={shots.length ? "click to enlarge" : undefined}>
          {shots.length ? (
            <>
              <Screenshots base={`/api/audits/${data.audit.id}/sites/${site.id}/screenshots`} names={shots} host={hostOf(site.final_url)} large />
              <p className="note">
                {cookie?.dismissed
                  ? "The cookie bar was closed before the screenshots were taken."
                  : cookie?.detected
                    ? "A cookie bar was found but could not be closed; it may cover part of the screenshots."
                    : "No cookie bar was found."}
              </p>
            </>
          ) : (
            <p className="muted">No screenshots: the browser checks did not run for this website.</p>
          )}
        </Card>
      </div>

      <div className="cols">
        <div className="col-main">
          <ProblemList problems={data.problems} />
          <div className="grid-2">
            <Card title="Competitors">
              <div className="stack">
                <span className="soft-icon">
                  <Users size={20} aria-hidden />
                </span>
                <p className="muted">No comparison yet. Competitors listed with an audit (the “konkurencia” CSV column) will be compared here in a later update.</p>
              </div>
            </Card>
            <Card title="Design review (AI)">
              <div className="stack">
                <span className="soft-icon">
                  <Eye size={20} aria-hidden />
                </span>
                <p className="muted">
                  Not evaluated. The design review by Claude arrives in a later update; it will need a Claude API key in <Link to="/settings">Settings</Link>.
                  The score is calculated without it.
                </p>
              </div>
            </Card>
          </div>
        </div>
        <div className="col-side">
          <Card title="At a glance">
            <dl className="facts">
              {data.facts.map((f) => (
                <div key={f.label} className="fact">
                  <dt>{f.label}</dt>
                  <dd>
                    <i style={{ background: TONE_COLOR[f.tone] }} aria-hidden />
                    {f.value}
                  </dd>
                </div>
              ))}
            </dl>
          </Card>
          <History data={data} />
        </div>
      </div>

      {data.contents.length > 0 && (
        <Card title="What the page contains" meta="homepage · also in the Claude Code export">
          <dl className="contents">
            {data.contents.map((c) => (
              <div key={c.label}>
                <dt>{c.label}</dt>
                <dd>{c.value}</dd>
              </div>
            ))}
          </dl>
        </Card>
      )}
    </>
  );
}

function ProblemList({ problems }: { problems: Problem[] }) {
  const [open, setOpen] = useState<string | null>(problems[0]?.check_id ?? null);
  const [all, setAll] = useState(false);
  const shown = all ? problems : problems.slice(0, SHOWN);
  return (
    <Card title="Problems, biggest impact first" meta={problems.length ? `${plural(problems.length, "problem")} · points of the total score each costs` : undefined}>
      {!problems.length ? (
        <p>No problems found.</p>
      ) : (
        <>
          <ul className="problems">
            {shown.map((p) => {
              const expanded = open === p.check_id;
              return (
                <li key={p.check_id}>
                  <button type="button" className="problem-head" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : p.check_id)}>
                    <span className="problem-pts num" title="Points of the total score this costs">
                      −{p.impact.toFixed(1)}
                      <small>pts</small>
                    </span>
                    <span className="problem-label">{p.label}</span>
                    <span className="problem-area">
                      <i style={{ background: AREA_DOT[p.area] ?? "var(--neutral)" }} aria-hidden />
                      {p.area_label}
                    </span>
                    {expanded ? <ChevronUp size={18} aria-hidden /> : <ChevronDown size={18} aria-hidden />}
                  </button>
                  {expanded && (
                    <div className="problem-body">
                      <p>{p.problem}</p>
                      {p.summary && <p className="muted">Found: {p.summary}</p>}
                      {p.where.length > 0 && (
                        <div>
                          <div className="mini-label">Where</div>
                          <div className="where">
                            {p.where.map((w) => (
                              <code key={w}>{w}</code>
                            ))}
                          </div>
                        </div>
                      )}
                      {p.solution && (
                        <div>
                          <div className="mini-label">What to do</div>
                          <p>{p.solution}</p>
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          {problems.length > SHOWN && (
            <Button size="sm" className="more-btn" onClick={() => setAll((v) => !v)}>
              {all ? "Show fewer" : `Show ${problems.length - SHOWN} more`}
            </Button>
          )}
        </>
      )}
    </Card>
  );
}

function History({ data }: { data: SiteView }) {
  const scored = data.history.filter((h) => h.score !== null);
  const current = data.history.find((h) => h.site_id === data.site.id);
  const previous = scored.find((h) => current && h.finished_at < current.finished_at);
  return (
    <Card title="Earlier audits">
      {data.history.length <= 1 ? (
        <p className="muted">This is the first audit of this website.</p>
      ) : (
        <>
          <ul className="history">
            {data.history.map((h) => (
              <li key={h.site_id}>
                <span className="history-date">
                  {h.site_id === data.site.id ? (
                    `${formatDate(h.finished_at)} · this audit`
                  ) : (
                    <Link to={`/audits/${h.audit_id}/sites/${h.site_id}`}>{formatDate(h.finished_at)}</Link>
                  )}
                </span>
                {h.score !== null ? <ScoreBadge score={h.score} category={h.category} /> : <span className="muted">{SITE_STATE_LABEL[h.state]}</span>}
              </li>
            ))}
          </ul>
          {previous && data.site.score !== null && previous.score !== null && (
            <p className="note">
              {data.site.score === previous.score
                ? `Same score as on ${formatDate(previous.finished_at)}`
                : `${data.site.score > previous.score ? "+" : "−"}${Math.abs(data.site.score - previous.score)} points since ${formatDate(previous.finished_at)}`}
            </p>
          )}
        </>
      )}
    </Card>
  );
}
