import { BookmarkPlus, Globe, MapPinned, Play, Search as SearchIcon, Trash2, UserPlus } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AreaCombobox } from "../components/AreaCombobox";
import { MapPreview } from "../components/MapPreview";
import { Banner, Button, Card, Checkbox, EmptyState, Field, PageHeader, Segmented, Select, Spinner, Tag, TextInput } from "../components/ui";
import {
  api,
  type AreaSuggestion,
  type CreateResult,
  type Estimate,
  type SearchOptions,
  type SearchParams,
  type SearchResponse,
  type SearchResult,
  type SearchTemplate,
} from "../lib/api";
import { formatDate, plural } from "../lib/format";
import { useToast } from "../lib/toast";
import { useApi } from "../lib/useApi";

type Tab = "with" | "without";
type Form = {
  country: string;
  area: AreaSuggestion | null;
  mode: "radius" | "region";
  radius: number;
  categoryId: string;
  query: string;
  google: boolean;
  osm: boolean;
};

const EMPTY: Form = { country: "", area: null, mode: "radius", radius: 15, categoryId: "", query: "", google: true, osm: true };

function toParams(form: Form): SearchParams | null {
  if (!form.country || !form.area || !(form.categoryId || form.query.trim()) || !(form.google || form.osm)) return null;
  return {
    country: form.country,
    area: form.area,
    mode: form.mode,
    radius_km: form.radius,
    category_id: form.query.trim() ? null : form.categoryId,
    query: form.query.trim() || null,
    sources: [form.google && "google", form.osm && "osm"].filter(Boolean) as SearchParams["sources"],
  };
}

function fromParams(params: SearchParams): Form {
  return {
    country: params.country,
    area: params.area,
    mode: params.mode,
    radius: params.radius_km,
    categoryId: params.category_id ?? "",
    query: params.query ?? "",
    google: params.sources.includes("google"),
    osm: params.sources.includes("osm"),
  };
}

export function Search() {
  const options = useApi<SearchOptions>("/api/search/options");
  const templates = useApi<SearchTemplate[]>("/api/search/templates");
  const [form, setForm] = useState<Form>(EMPTY);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [lastParams, setLastParams] = useState<SearchParams | null>(null);
  const [runId, setRunId] = useState(0);
  const [templateName, setTemplateName] = useState<string | null>(null);
  const toast = useToast();

  const opts = options.data;
  const params = useMemo(() => toParams(form), [form]);
  const categoryLabel = opts?.categories.find((c) => c.id === form.categoryId)?.label;
  const regionPossible = Boolean(form.area && (form.area.osm_relation || form.area.bbox));
  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));

  useEffect(() => {
    if (opts && !opts.google_configured) setForm((f) => ({ ...f, google: false }));
  }, [opts]);

  useEffect(() => {
    if (!params) {
      setEstimate(null);
      return;
    }
    const timer = window.setTimeout(() => {
      api<Estimate>("/api/search/estimate", { body: params })
        .then(setEstimate)
        .catch(() => setEstimate(null));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [params]);

  function suggestedName(): string {
    const what = form.query.trim() || categoryLabel || "Businesses";
    const where = form.area?.label.split(",")[0] ?? "";
    return form.mode === "region" ? `${what} ${where}` : `${what} ${where} + ${form.radius} km`;
  }

  async function run(event: FormEvent) {
    event.preventDefault();
    if (!params) return;
    setRunning(true);
    setError(null);
    try {
      const result = await api<SearchResponse>("/api/search/run", { body: params });
      setResponse(result);
      setLastParams(params);
      setRunId((n) => n + 1);
      if (estimate?.google_requests_max) setEstimate(null); // usage changed; recomputed on the next edit
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed");
    } finally {
      setRunning(false);
    }
  }

  async function saveTemplate() {
    if (!params || !templateName?.trim()) return;
    try {
      await api("/api/search/templates", { body: { name: templateName.trim(), params } });
      toast(`Template “${templateName.trim()}” saved`);
      setTemplateName(null);
      void templates.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save the template", "error");
    }
  }

  async function deleteTemplate(template: SearchTemplate) {
    try {
      await api(`/api/search/templates/${template.id}`, { method: "DELETE" });
      toast(`Template “${template.name}” deleted`);
      void templates.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not delete the template", "error");
    }
  }

  if (options.error) return <Banner kind="error">{options.error.message}</Banner>;
  if (!opts) return <Spinner />;

  return (
    <>
      <PageHeader
        eyebrow="Find businesses"
        title="Search"
        sub="Find businesses by category and area, then send the ones with a website to an audit and the ones without to your customer list."
      />
      <div className="grid-2" style={{ alignItems: "start" }}>
        <Card title="What and where">
          <form className="stack" onSubmit={run}>
            {templates.data && templates.data.length > 0 && (
              <TemplatePicker templates={templates.data} onLoad={(t) => setForm(fromParams(t.params))} onDelete={deleteTemplate} />
            )}
            <div className="form-grid">
              <Field label="Country" hint="Limits the search, so a town name never matches another country.">
                {(id, describedBy) => (
                  <Select
                    id={id}
                    aria-describedby={describedBy}
                    value={form.country}
                    onChange={(e) => set({ country: e.target.value, area: null, mode: "radius" })}
                    required
                  >
                    <option value="" disabled>
                      Choose a country
                    </option>
                    {opts.countries.map((c) => (
                      <option key={c.code} value={c.code}>
                        {c.name}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label="Town, district or region">
                {(id, describedBy) => (
                  <AreaCombobox
                    id={id}
                    describedBy={describedBy}
                    country={form.country}
                    value={form.area}
                    onChange={(area) => set({ area, mode: area?.kind === "region" && (area.osm_relation || area.bbox) ? "region" : "radius" })}
                  />
                )}
              </Field>
            </div>

            {regionPossible && (
              <Segmented<Form["mode"]>
                label="Search area"
                value={form.mode}
                onChange={(mode) => set({ mode })}
                options={[
                  { value: "radius", label: "Radius" },
                  { value: "region", label: form.area?.kind === "region" ? "Whole district / region" : "Whole town" },
                ]}
              />
            )}
            {form.mode === "radius" && (
              <Field label={`Radius: ${form.radius} km`} hint={regionPossible ? undefined : "To search a whole district or region, pick it in the field above."}>
                {(id, describedBy) => (
                  <input
                    id={id}
                    aria-describedby={describedBy}
                    className="range"
                    type="range"
                    min={opts.radius_km.min}
                    max={opts.radius_km.max}
                    step={5}
                    value={form.radius}
                    onChange={(e) => set({ radius: Number(e.target.value) })}
                  />
                )}
              </Field>
            )}

            <div className="form-grid">
              <Field label="Category">
                {(id) => (
                  <Select id={id} value={form.categoryId} onChange={(e) => set({ categoryId: e.target.value, query: "" })}>
                    <option value="">Choose a category</option>
                    {opts.categories.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label="Or search by keyword" hint="Replaces the category, e.g. “pneuservis”.">
                {(id, describedBy) => (
                  <TextInput
                    id={id}
                    aria-describedby={describedBy}
                    value={form.query}
                    maxLength={80}
                    onChange={(e) => set({ query: e.target.value, categoryId: e.target.value ? "" : form.categoryId })}
                  />
                )}
              </Field>
            </div>

            <fieldset className="fieldset">
              <legend className="field-label">Sources</legend>
              <div className="row">
                <Checkbox
                  label="Google Places"
                  checked={form.google}
                  disabled={!opts.google_configured}
                  onChange={(e) => set({ google: e.target.checked })}
                />
                <Checkbox label="OpenStreetMap (free)" checked={form.osm} onChange={(e) => set({ osm: e.target.checked })} />
              </div>
              {!opts.google_configured && (
                <span className="field-hint">
                  Google Places needs an API key in <Link to="/settings">Settings</Link>. OpenStreetMap is free but has fewer businesses.
                </span>
              )}
            </fieldset>

            {estimate && <Banner kind={estimate.over_free_limit ? "warn" : "info"}>{estimate.message}</Banner>}
            {error && <Banner kind="error">{error}</Banner>}

            {templateName === null ? (
              <div className="row">
                <Button type="submit" variant="primary" icon={SearchIcon} loading={running} disabled={!params}>
                  Search
                </Button>
                <Button icon={BookmarkPlus} disabled={!params} onClick={() => setTemplateName(suggestedName())}>
                  Save as template
                </Button>
              </div>
            ) : (
              <div className="row" role="group" aria-label="Save as template">
                <TextInput
                  aria-label="Template name"
                  value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)}
                  maxLength={200}
                  style={{ flex: 1, minWidth: 200 }}
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault(); // don't submit the search form
                      void saveTemplate();
                    }
                  }}
                />
                <Button variant="primary" onClick={() => void saveTemplate()} disabled={!templateName.trim()}>
                  Save
                </Button>
                <Button variant="ghost" onClick={() => setTemplateName(null)}>
                  Cancel
                </Button>
              </div>
            )}
          </form>
        </Card>
        <Card title="Area preview" meta={form.area ? (form.mode === "region" ? "whole area" : `${form.radius} km radius`) : undefined}>
          <MapPreview tileUrl={opts.map_tile_url} area={form.area} mode={form.mode} radiusKm={form.radius} />
        </Card>
      </div>

      {running && !response && <Spinner label="Searching – OpenStreetMap can take up to half a minute" />}
      {response && lastParams && <Results key={runId} response={response} params={lastParams} projectName={suggestedName()} />}
    </>
  );
}

function TemplatePicker({ templates, onLoad, onDelete }: { templates: SearchTemplate[]; onLoad: (t: SearchTemplate) => void; onDelete: (t: SearchTemplate) => void }) {
  const [selected, setSelected] = useState("");
  const template = templates.find((t) => String(t.id) === selected);
  return (
    <Field label="Template">
      {(id) => (
        <div className="input-group">
          <Select
            id={id}
            value={selected}
            onChange={(e) => {
              setSelected(e.target.value);
              const t = templates.find((x) => String(x.id) === e.target.value);
              if (t) onLoad(t);
            }}
          >
            <option value="">Load a saved search…</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </Select>
          <Button
            icon={Trash2}
            aria-label={template ? `Delete template ${template.name}` : "Delete template"}
            disabled={!template}
            onClick={() => {
              if (template) {
                onDelete(template);
                setSelected("");
              }
            }}
          />
        </div>
      )}
    </Field>
  );
}

function KnownTag({ result }: { result: SearchResult }) {
  if (!result.known) return <span className="muted">New</span>;
  if (result.known.do_not_contact) return <Tag color="var(--danger)">Do not contact</Tag>;
  return (
    <Tag color="var(--accent)">{result.known.last_audit_at ? `In your list · audited ${formatDate(result.known.last_audit_at)}` : "In your list"}</Tag>
  );
}

function Results({ response, params, projectName }: { response: SearchResponse; params: SearchParams; projectName: string }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>(response.counts.with_website || !response.counts.without_website ? "with" : "without");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [results, setResults] = useState(response.results);
  const [project, setProject] = useState(projectName);
  const [busy, setBusy] = useState(false);
  const [confirmDnc, setConfirmDnc] = useState(false);

  const rows = results.filter((r) => (tab === "with" ? r.website : !r.website));
  const selectable = rows.filter((r) => !r.known?.do_not_contact);
  const chosen = rows.filter((r) => selected.has(r.key));
  const chosenDnc = chosen.filter((r) => r.known?.do_not_contact).length;
  const allSelected = selectable.length > 0 && selectable.every((r) => selected.has(r.key));
  const usesGoogle = response.sources.google > 0;

  function toggle(key: string) {
    setConfirmDnc(false);
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleAll() {
    setConfirmDnc(false);
    setSelected((s) => {
      const next = new Set(s);
      for (const r of selectable) {
        if (allSelected) next.delete(r.key);
        else next.add(r.key);
      }
      return next;
    });
  }

  async function send() {
    if (chosenDnc && !confirmDnc) {
      setConfirmDnc(true);
      return;
    }
    setBusy(true);
    const items = chosen.map((r) => ({ website: r.website, place_id: r.place_id, osm_id: r.osm_id, osm_name: r.osm_name }));
    try {
      if (tab === "with") {
        const result = await api<CreateResult>("/api/search/to-audit", { body: { project: project || null, items } });
        if (result.skipped_duplicates) toast(`${plural(result.skipped_duplicates, "duplicate")} skipped`);
        if (result.audit) navigate(`/audits/${result.audit.id}`);
      } else {
        const result = await api<{ leads: number }>("/api/search/to-leads", { body: { project: project || null, items } });
        toast(`${plural(result.leads, "business", "businesses")} added to Customers as “no website”`);
        const added = new Set(chosen.map((r) => r.key));
        setResults((list) => list.map((r) => (added.has(r.key) && !r.known ? { ...r, known: { company_id: 0, do_not_contact: false, last_audit_at: null } } : r)));
        setSelected(new Set());
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "Something went wrong", "error");
    } finally {
      setBusy(false);
      setConfirmDnc(false);
    }
  }

  return (
    <Card
      title="Results"
      meta={`${plural(response.counts.total, "business", "businesses")} · Google ${response.sources.google} · OpenStreetMap ${response.sources.osm}`}
    >
      <div className="stack">
        {response.warnings.map((w) => (
          <Banner key={w} kind="warn">
            {w}
          </Banner>
        ))}
        {response.counts.total === 0 ? (
          <EmptyState icon={MapPinned} title="No businesses found">
            Try a larger radius, another category or a keyword. OpenStreetMap has fewer businesses than Google, so adding a Google Places key in Settings
            usually helps.
          </EmptyState>
        ) : (
          <>
            <div className="row">
              <Segmented<Tab>
                label="Results"
                value={tab}
                onChange={(t) => {
                  setTab(t);
                  setConfirmDnc(false);
                }}
                options={[
                  { value: "with", label: `Has website (${response.counts.with_website})` },
                  { value: "without", label: `No website (${response.counts.without_website})` },
                ]}
              />
              <span className="spacer" />
              <TextInput aria-label="Project name" placeholder="Project" value={project} onChange={(e) => setProject(e.target.value)} style={{ width: 260 }} />
              <Button variant="primary" icon={tab === "with" ? Play : UserPlus} disabled={!chosen.length} loading={busy} onClick={send}>
                {tab === "with" ? `Send ${chosen.length || ""} to audit` : `Add ${chosen.length || ""} to customers`}
              </Button>
            </div>
            {confirmDnc && (
              <Banner kind="warn">
                {plural(chosenDnc, "selected business is", "selected businesses are")} marked “Do not contact”. Click the button again to include them anyway.
              </Banner>
            )}
            {rows.length === 0 ? (
              <p className="muted">{tab === "with" ? "None of the businesses found list a website." : "Every business found lists a website."}</p>
            ) : (
              <div className="table-box">
                <table className="table" style={{ minWidth: 640 }}>
                  <thead>
                    <tr>
                      <th className="check-col">
                        <input type="checkbox" aria-label="Select all" checked={allSelected} onChange={toggleAll} disabled={!selectable.length} />
                      </th>
                      <th>Business</th>
                      {tab === "with" && <th>Website</th>}
                      <th>{params.mode === "region" ? "Source" : "Distance"}</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.key} className="clickable" onClick={() => toggle(r.key)}>
                        <td className="check-col" onClick={(e) => e.stopPropagation()}>
                          <input type="checkbox" aria-label={`Select ${r.name}`} checked={selected.has(r.key)} onChange={() => toggle(r.key)} />
                        </td>
                        <td>
                          <span className="cell-main">{r.name}</span>
                          {r.category && <span className="cell-sub">{r.category}</span>}
                        </td>
                        {tab === "with" && (
                          <td>
                            <a href={r.website ?? undefined} target="_blank" rel="noreferrer noopener" onClick={(e) => e.stopPropagation()} className="row" style={{ gap: 6 }}>
                              <Globe size={14} aria-hidden />
                              {r.domain}
                            </a>
                          </td>
                        )}
                        <td className="num">
                          {params.mode === "region" ? null : r.distance_km !== null ? `${r.distance_km.toFixed(1)} km` : "—"}
                          <span className="cell-sub">{r.sources.map((s) => (s === "google" ? "Google" : "OSM")).join(" + ")}</span>
                        </td>
                        <td>
                          <KnownTag result={r} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
        <p className="attribution">
          {usesGoogle && <span>Business data from Google Maps. </span>}
          {response.attribution && (
            <span>
              Data from{" "}
              <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
                {response.attribution}
              </a>
              .
            </span>
          )}
        </p>
      </div>
    </Card>
  );
}
