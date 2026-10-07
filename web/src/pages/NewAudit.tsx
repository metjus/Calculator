import { FileUp, Play } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Banner, Button, Card, Checkbox, Field, PageHeader, Segmented, TextArea, TextInput } from "../components/ui";
import { api, ApiError, type AiEstimate, type CreateResult, type SettingsData } from "../lib/api";
import { plural, usd } from "../lib/format";
import { useToast } from "../lib/toast";
import { useApi } from "../lib/useApi";

type Source = "paste" | "csv";

export function NewAudit() {
  const navigate = useNavigate();
  const toast = useToast();
  const settings = useApi<SettingsData>("/api/settings");
  const [source, setSource] = useState<Source>("paste");
  const [project, setProject] = useState("");
  const [urls, setUrls] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [invalid, setInvalid] = useState<CreateResult["invalid"]>([]);
  const [aiReview, setAiReview] = useState(false);
  const [competitors, setCompetitors] = useState("");
  const [csvRows, setCsvRows] = useState(0);
  const fileInput = useRef<HTMLInputElement>(null);

  const urlCount = urls.split(/[\s,;]+/).filter(Boolean).length;
  const siteCount = source === "paste" ? urlCount : csvRows;
  const estimate = useApi<AiEstimate>(`/api/audits/ai-estimate?sites=${siteCount}`);
  const claudeReady = Boolean(settings.data?.keys.claude.configured);
  const pagespeedReady = Boolean(settings.data?.keys.pagespeed.configured);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setInvalid([]);
    try {
      let result: CreateResult;
      if (source === "paste") {
        result = await api<CreateResult>("/api/audits", { body: { project: project || null, urls, ai_review: aiReview, competitors } });
      } else {
        if (!file) throw new Error("Choose a CSV file");
        const form = new FormData();
        form.append("file", file);
        if (project) form.append("project", project);
        form.append("ai_review", String(aiReview));
        form.append("competitors", competitors);
        result = await api<CreateResult>("/api/audits/csv", { body: form });
      }
      const notes = [
        result.no_website_leads && `${plural(result.no_website_leads, "business")} without a website added to Customers`,
        result.skipped_duplicates && `${plural(result.skipped_duplicates, "duplicate")} skipped`,
        result.invalid.length && `${plural(result.invalid.length, "entry", "entries")} skipped (not a web address)`,
      ].filter(Boolean);
      if (notes.length) toast(notes.join(" · "));
      if (result.audit) navigate(`/audits/${result.audit.id}`);
      else navigate("/customers");
    } catch (e) {
      if (e instanceof ApiError && e.detail && typeof e.detail === "object" && "invalid" in e.detail) {
        setInvalid((e.detail as { invalid: CreateResult["invalid"] }).invalid);
      }
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader eyebrow="Audits" title="New audit" sub="Websites are checked in the background, two at a time, politely and within a time limit each." />
      <form onSubmit={submit} className="grid-2" style={{ alignItems: "start" }}>
        <Card title="Websites">
          <div className="stack">
            <Segmented<Source>
              label="Input"
              value={source}
              onChange={setSource}
              options={[
                { value: "paste", label: "Paste addresses" },
                { value: "csv", label: "Upload CSV" },
              ]}
            />
            {source === "paste" ? (
              <Field label="Website addresses" hint={urlCount ? `${plural(urlCount, "address", "addresses")} · one per line, or separated by commas` : "One per line, or separated by commas"}>
                {(id, describedBy) => (
                  <TextArea
                    id={id}
                    aria-describedby={describedBy}
                    placeholder={"kadernictvo-lena.sk\nautoservis-novak.sk"}
                    value={urls}
                    onChange={(e) => setUrls(e.target.value)}
                  />
                )}
              </Field>
            ) : (
              <Field
                label="CSV file"
                hint={
                  <>
                    Columns: <code>url</code>, <code>nazov_firmy</code> (optional), <code>konkurencia</code> (competitor URLs, optional), <code>projekt</code>. Rows
                    without a URL become “no website” leads. Comma or semicolon separated, UTF-8 or Windows-1250.
                  </>
                }
              >
                {(id, describedBy) => (
                  <div className="row">
                    <input
                      ref={fileInput}
                      id={id}
                      type="file"
                      accept=".csv,text/csv"
                      className="sr-only"
                      aria-describedby={describedBy}
                      onChange={async (e) => {
                        const chosen = e.target.files?.[0] ?? null;
                        setFile(chosen);
                        // Rough count for the AI estimate: non-empty lines minus the header.
                        const lines = chosen ? (await chosen.text()).split(/\r?\n/).filter((l) => l.trim()).length : 0;
                        setCsvRows(Math.max(0, lines - 1));
                      }}
                    />
                    <Button icon={FileUp} onClick={() => fileInput.current?.click()}>
                      Choose file
                    </Button>
                    <span className={file ? "" : "muted"}>{file ? file.name : "No file chosen"}</span>
                  </div>
                )}
              </Field>
            )}
            {error && <Banner kind="error">{error}</Banner>}
            {invalid.length > 0 && (
              <Banner kind="warn">
                Not readable: {invalid.slice(0, 6).map((i) => `“${i.input}”`).join(", ")}
                {invalid.length > 6 ? ` and ${invalid.length - 6} more` : ""}
              </Banner>
            )}
          </div>
        </Card>
        <Card title="Options">
          <div className="stack">
            <Field label="Project" hint="Groups the results, e.g. “Hair salons Trnava”. A project column in the CSV overrides it per row.">
              {(id, describedBy) => <TextInput id={id} aria-describedby={describedBy} value={project} onChange={(e) => setProject(e.target.value)} maxLength={200} />}
            </Field>
            <Field
              label="Competitors (optional)"
              hint="Compared with every website in this audit, up to 5. Each is scanned once, without the AI review. Per-website competitors: the CSV column “konkurencia”."
            >
              {(id, describedBy) => (
                <TextArea
                  id={id}
                  aria-describedby={describedBy}
                  rows={2}
                  placeholder={"salon-viva.sk\nstrih-studio.sk"}
                  value={competitors}
                  onChange={(e) => setCompetitors(e.target.value)}
                />
              )}
            </Field>
            <Checkbox
              label="Evaluate design with Claude (AI)"
              disabled={!claudeReady}
              checked={claudeReady && aiReview}
              onChange={(e) => setAiReview(e.target.checked)}
              hint={
                claudeReady ? (
                  <>
                    Claude looks at the desktop and mobile screenshots of each website; the score then includes the design.{" "}
                    {estimate.data &&
                      (siteCount > 0
                        ? `Estimated cost: ${usd(estimate.data.total_usd.low)}–${usd(estimate.data.total_usd.high)} for ${plural(siteCount, "website")}, paid from your Claude account.`
                        : `About ${usd(estimate.data.per_site_usd.low)}–${usd(estimate.data.per_site_usd.high)} per website, paid from your Claude account.`)}
                  </>
                ) : (
                  <>
                    Needs a Claude API key in <Link to="/settings">Settings</Link>.
                  </>
                )
              }
            />
            {!pagespeedReady && settings.data && (
              <Banner>
                Speed is measured without Google PageSpeed until you add a key in <Link to="/settings">Settings</Link>.
              </Banner>
            )}
            <div className="row">
              <Button type="submit" variant="primary" icon={Play} loading={busy} disabled={source === "paste" ? urlCount === 0 : !file}>
                Start audit
              </Button>
            </div>
          </div>
        </Card>
      </form>
    </>
  );
}
