import { Check, ChevronDown, ChevronRight, ChevronUp, ExternalLink, Eye, FileDown, RotateCw, SquareTerminal, TriangleAlert, Users } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { claudePrompt, copyText, exportUrl, Screenshots } from "../components/SiteParts";
import { Banner, Button, Card, PageHeader, ScoreBadge, Spinner, Tag } from "../components/ui";
import { api, type Category, type CompareRow, type ManualDecision, type Problem, type SiteView } from "../lib/api";
import { CATEGORY_LABEL, CATEGORY_VAR, formatDate, hostOf, plural, SITE_STATE_LABEL, usd } from "../lib/format";
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
  return <Detail data={view.data} reload={view.reload} onUpdate={view.setData} />;
}

function Detail({ data, reload, onUpdate }: { data: SiteView; reload: () => Promise<void>; onUpdate: (view: SiteView) => void }) {
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
      {!scored ? <NotScored data={data} reload={reload} /> : <Scored data={data} onUpdate={onUpdate} />}
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

function Scored({ data, onUpdate }: { data: SiteView; onUpdate: (view: SiteView) => void }) {
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
          <AiReviewCard data={data} onUpdate={onUpdate} />
          <ComparisonCard data={data} />
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

/** Category of a 0–100 value, with the same limits as the website score. */
function categoryOf(value: number): Category {
  return value >= 80 ? "good" : value >= 60 ? "ok" : value >= 40 ? "weak" : "critical";
}

const LANGUAGE_NAME: Record<string, string> = { sk: "Slovak", cs: "Czech", en: "English" };

function AiReviewCard({ data, onUpdate }: { data: SiteView; onUpdate: (view: SiteView) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const review = data.ai_review;
  const done = review && typeof review.score === "number";
  const failed = review && !done && review.summary.startsWith("AI design review failed");
  const price = `${usd(data.ai.per_site_usd.low)}–${usd(data.ai.per_site_usd.high)}`;

  async function run() {
    setBusy(true);
    try {
      onUpdate(await api<SiteView>(`/api/audits/${data.audit.id}/sites/${data.site.id}/ai-review`, { method: "POST" }));
      toast("Design reviewed – the score now includes it");
    } catch (e) {
      toast(e instanceof Error ? e.message : "The review failed", "error");
    } finally {
      setBusy(false);
    }
  }

  const action = data.ai.configured ? (
    <div className="row">
      <Button icon={Eye} variant={done ? "ghost" : "secondary"} size={done ? "sm" : "md"} loading={busy} onClick={run}>
        {done ? "Review again" : "Review design with Claude"}
      </Button>
      <span className="muted">{busy ? "Claude is looking at the screenshots – this can take up to a minute." : `about ${price}, paid from your Claude account`}</span>
    </div>
  ) : (
    <p className="muted">
      Add a Claude API key in <Link to="/settings">Settings</Link> to let Claude review the design from the screenshots.
    </p>
  );

  if (!done) {
    return (
      <Card title="Design review (AI)">
        <div className="stack">
          {failed ? (
            <Banner kind="warn">{review!.summary}</Banner>
          ) : (
            <p className="muted">Not evaluated yet. The score is calculated without the design review until Claude has looked at the screenshots.</p>
          )}
          {action}
        </div>
      </Card>
    );
  }
  const category = categoryOf(review.score!);
  return (
    <Card
      title="Design review (AI)"
      meta={[review.model && `by ${review.model}`, review.cost_usd !== undefined && usd(review.cost_usd)].filter(Boolean).join(" · ")}
    >
      <div className="stack">
        <div className="ai-head">
          <span className="score" style={{ ["--cat" as string]: CATEGORY_VAR[category] }}>
            <b>{review.score}</b>
            {CATEGORY_LABEL[category]}
          </span>
          <p className="ai-verdict">{review.verdict}</p>
        </div>
        <div className="ai-lists">
          {review.strengths && review.strengths.length > 0 && (
            <div>
              <div className="mini-label">Works well</div>
              <ul className="ai-list">
                {review.strengths.map((item) => (
                  <li key={item}>
                    <Check size={16} className="ai-good" aria-hidden />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {review.weaknesses && review.weaknesses.length > 0 && (
            <div>
              <div className="mini-label">To improve</div>
              <ul className="ai-list">
                {review.weaknesses.map((item) => (
                  <li key={item}>
                    <TriangleAlert size={16} className="ai-bad" aria-hidden />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <p className="note" style={{ marginTop: 0 }}>
          Written in {LANGUAGE_NAME[review.language ?? "sk"] ?? review.language} for the client report. The design counts {data.areas.find((a) => a.area === "design_ai")?.weight ?? 10} % of the score.
        </p>
        {action}
      </div>
    </Card>
  );
}

function YesNo({ value }: { value: boolean | null }) {
  if (value === null) return <span className="muted">—</span>;
  return <Tag color={value ? "var(--neutral)" : "var(--crit)"}>{value ? "Yes" : "No"}</Tag>;
}

function ComparisonCard({ data }: { data: SiteView }) {
  const { comparison, site, areas } = data;
  const fromAudit = comparison.source === "audit";
  const self: CompareRow = { ...comparison.self, domain: hostOf(site.final_url ?? site.input_url), url: site.final_url ?? site.input_url, state: site.state, score: site.score, category: site.category };
  const rows = comparison.rows;
  const scored = rows.filter((r) => r.score !== null);
  // Areas where the best compared website is clearly ahead.
  const ahead = areas
    .filter((a) => a.score !== null)
    .map((a) => ({ label: a.label, gap: Math.max(0, ...scored.map((r) => (r.areas[a.area] ?? 0) - (a.score ?? 0))) }))
    .filter((a) => a.gap >= 10)
    .sort((a, b) => b.gap - a.gap)
    .slice(0, 3);
  const withShots = rows.filter((r) => r.id && r.screenshots && r.screenshots.length);

  return (
    <Card title={fromAudit ? "Compared with this audit" : "Competitors"} meta={fromAudit ? "the best other websites in the same audit" : "scanned with this audit"}>
      {!rows.length ? (
        <div className="stack">
          <span className="soft-icon">
            <Users size={20} aria-hidden />
          </span>
          <p className="muted">
            No competitors to compare with. List competitor addresses when you start an audit (or in the CSV column “konkurencia”); they are scanned once,
            without the AI review.
          </p>
        </div>
      ) : (
        <div className="stack">
          <div className="table-box">
            <table className="table" style={{ minWidth: 520 }}>
              <thead>
                <tr>
                  <th>Website</th>
                  <th>Score</th>
                  <th>Mobile layout</th>
                  <th>PageSpeed</th>
                  <th>HTTPS</th>
                </tr>
              </thead>
              <tbody>
                {[self, ...rows].map((r, i) => (
                  <tr key={`${r.domain}-${i}`} className={i === 0 ? "row-self" : undefined}>
                    <td>
                      <span className="cell-main">{r.domain}</span>
                      {i === 0 && <span className="cell-sub">this website</span>}
                      {i > 0 && r.site_id && (
                        <Link className="cell-sub" to={`/audits/${data.audit.id}/sites/${r.site_id}`}>
                          open detail
                        </Link>
                      )}
                    </td>
                    <td>
                      {r.score !== null ? (
                        <ScoreBadge score={r.score} category={r.category} />
                      ) : (
                        <span className="muted">{r.state === "pending" ? "not scanned" : SITE_STATE_LABEL[r.state as keyof typeof SITE_STATE_LABEL] ?? r.reason}</span>
                      )}
                    </td>
                    <td>
                      <YesNo value={r.mobile} />
                    </td>
                    <td className="num">{r.pagespeed ?? <span className="muted">—</span>}</td>
                    <td>
                      <YesNo value={r.https} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {scored.length > 0 && (
            <p className="note" style={{ marginTop: 0 }}>
              {ahead.length
                ? `Where the others do better: ${ahead.map((a) => `${a.label} (+${a.gap})`).join(", ")}.`
                : "This website is level with or ahead of the others in every area."}
            </p>
          )}
          {withShots.length > 0 && (
            <div className="competitor-shots">
              {withShots.map((r) => (
                <div key={r.id} className="competitor-shot">
                  <span className="mini-label">{r.domain}</span>
                  <Screenshots base={`/api/audits/${data.audit.id}/competitors/${r.id}/screenshots`} names={r.screenshots!} host={r.domain} />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
