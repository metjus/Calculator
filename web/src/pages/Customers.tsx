import { Search, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Banner, Card, EmptyState, PageHeader, Segmented, Spinner, Tag, TextInput } from "../components/ui";
import type { Company } from "../lib/api";
import { formatDate } from "../lib/format";
import { useApi } from "../lib/useApi";

type Filter = "all" | "website" | "none";
const SOURCE_LABEL: Record<Company["source"], string> = { google: "Google Maps", osm: "OpenStreetMap", manual: "Added by you" };

function displayName(c: Company): string {
  // Google-sourced businesses keep only their place_id; the name is reloaded on the customer card (stage 7).
  return c.name ?? c.domain ?? (c.source === "google" ? "Business from Google Maps" : "Unnamed business");
}

export function Customers() {
  const companies = useApi<Company[]>("/api/companies");
  const [filter, setFilter] = useState<Filter>("all");
  const [text, setText] = useState("");
  const all = companies.data ?? [];
  const counts = { all: all.length, website: all.filter((c) => c.has_website).length, none: all.filter((c) => !c.has_website).length };

  const rows = useMemo(() => {
    const q = text.trim().toLowerCase();
    return (companies.data ?? []).filter(
      (c) =>
        (filter === "all" || (filter === "website") === c.has_website) &&
        (!q || [c.name, c.domain, c.project].some((v) => v?.toLowerCase().includes(q))),
    );
  }, [companies.data, filter, text]);

  return (
    <>
      <PageHeader
        eyebrow="CRM"
        title="Customers"
        sub="Every business from your audits and searches. Statuses, notes and reminders arrive with the CRM stage."
        actions={
          <Link to="/search" className="btn">
            <Search size={16} aria-hidden /> Find businesses
          </Link>
        }
      />
      {companies.error && <Banner kind="error">{companies.error.message}</Banner>}
      {companies.loading && !companies.data ? (
        <Spinner />
      ) : all.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No customers yet"
          action={
            <div className="row">
              <Link to="/search" className="btn btn-primary">
                <Search size={16} aria-hidden /> Find businesses
              </Link>
              <Link to="/audits/new" className="btn">
                New audit
              </Link>
            </div>
          }
        >
          Businesses appear here when you audit their website or add them from a search. Businesses without a website are kept as leads for a new
          website.
        </EmptyState>
      ) : (
        <Card>
          <div className="stack">
            <div className="row">
              <Segmented<Filter>
                label="Website filter"
                value={filter}
                onChange={setFilter}
                options={[
                  { value: "all", label: `All (${counts.all})` },
                  { value: "website", label: `Has website (${counts.website})` },
                  { value: "none", label: `No website (${counts.none})` },
                ]}
              />
              <span className="spacer" />
              <TextInput type="search" aria-label="Search customers" placeholder="Search name, domain or project" value={text} onChange={(e) => setText(e.target.value)} style={{ width: 280 }} />
            </div>
            <div className="table-box">
              <table className="table" style={{ minWidth: 640 }}>
                <thead>
                  <tr>
                    <th>Business</th>
                    <th>Project</th>
                    <th>Website</th>
                    <th>Last score</th>
                    <th>Added</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <span className="cell-main">{displayName(c)}</span>
                        <span className="cell-sub">
                          {SOURCE_LABEL[c.source]}
                          {c.do_not_contact && (
                            <>
                              {" · "}
                              <Tag color="var(--danger)">Do not contact</Tag>
                            </>
                          )}
                        </span>
                      </td>
                      <td>{c.project ?? <span className="muted">—</span>}</td>
                      <td>
                        {c.url ? (
                          <a href={c.url} target="_blank" rel="noreferrer noopener">
                            {c.domain}
                          </a>
                        ) : (
                          <Tag color="var(--weak)">No website</Tag>
                        )}
                      </td>
                      <td className="num">
                        {c.last_score !== null && c.last_audit_id !== null ? (
                          <Link to={`/audits/${c.last_audit_id}`}>{c.last_score} / 100</Link>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td className="num">{formatDate(c.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rows.length === 0 && <p className="muted">No customers match this filter.</p>}
          </div>
        </Card>
      )}
    </>
  );
}
