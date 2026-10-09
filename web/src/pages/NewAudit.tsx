import { ClipboardCopy, Play } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Banner, Button, Card, Checkbox, DropZone, Field, PageHeader, Segmented, TextArea, TextInput } from "../components/ui";
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
  // Businesses marked "do not contact" are never audited without a word (the brief).
  const [blocked, setBlocked] = useState<CreateResult["blocked"]>([]);
  const [madeAudit, setMadeAudit] = useState<number | null>(null);
  const [aiReview, setAiReview] = useState(false);
  const [competitors, setCompetitors] = useState("");
  const [csvRows, setCsvRows] = useState(0);
  // A design review written in the Claude app before the audit runs: it waits with the audit and
  // is applied to each website the moment that website has been scanned.
  const [reviews, setReviews] = useState<{ text: string; name: string; rows: number } | null>(null);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [preparing, setPreparing] = useState(false);

  async function copyReviewPrompt() {
    setPreparing(true);
    try {
      const text = source === "paste" ? urls : file ? await file.text() : "";
      const got = await api<{ prompt: string; websites: string[] }>("/api/audits/ai-review/prompt", { body: { urls: text } });
      try {
        await navigator.clipboard.writeText(got.prompt);
        toast(`Prompt for ${plural(got.websites.length, "website")} copied — paste it into Claude`);
      } catch {
        setPrompt(got.prompt);  // no clipboard permission: show it to copy by hand
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "The prompt could not be prepared", "error");
    } finally {
      setPreparing(false);
    }
  }

  async function takeReviews(chosen: File) {
    const text = await chosen.text();
    const rows = text.split(/\r?\n/).filter((line) => line.trim()).length - 1;
    setReviews({ text, name: chosen.name, rows: Math.max(0, rows) });
    setPrompt(null);
    toast(`${plural(Math.max(0, rows), "review")} ready — they are applied when each website is scanned`);
  }

  async function takeCsv(chosen: File) {
    setFile(chosen);
    setError(null);
    // Rough count for the AI estimate: non-empty lines minus the header.
    const lines = (await chosen.text()).split(/\r?\n/).filter((line) => line.trim()).length;
    setCsvRows(Math.max(0, lines - 1));
  }

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
    setBlocked([]);
    try {
      let result: CreateResult;
      if (source === "paste") {
        result = await api<CreateResult>("/api/audits", {
          body: { project: project || null, urls, ai_review: aiReview, competitors, reviews: reviews?.text ?? "" },
        });
      } else {
        if (!file) throw new Error("Choose a CSV file");
        const form = new FormData();
        form.append("file", file);
        if (project) form.append("project", project);
        form.append("ai_review", String(aiReview));
        form.append("competitors", competitors);
        if (reviews) form.append("reviews", reviews.text);
        result = await api<CreateResult>("/api/audits/csv", { body: form });
      }
      const notes = [
        result.no_website_leads && `${plural(result.no_website_leads, "business")} without a website added to Customers`,
        result.skipped_duplicates && `${plural(result.skipped_duplicates, "duplicate")} skipped`,
        result.reviews && `${plural(result.reviews, "design review")} attached`,
        result.unknown_reviews.length && `${plural(result.unknown_reviews.length, "review")} matched no website here`,
        result.known.length && `${plural(result.known.length, "business")} you have already approached`,
        result.invalid.length && `${plural(result.invalid.length, "entry", "entries")} skipped (not a web address)`,
      ].filter(Boolean);
      if (notes.length) toast(notes.join(" · "));
      if (result.blocked.length) {
        // Stay here and say who was left out, so the decision is the user's.
        setBlocked(result.blocked);
        setMadeAudit(result.audit?.id ?? null);
        return;
      }
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

  /** The second half of the "do not contact" decision: audit them after all. */
  async function auditBlocked() {
    setBusy(true);
    try {
      const result = await api<CreateResult>("/api/audits", {
        body: {
          project: project || null,
          urls: blocked.map((row) => row.url).join(" "),
          ai_review: aiReview,
          competitors,
          allow_do_not_contact: true,
        },
      });
      if (result.audit) navigate(`/audits/${result.audit.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader eyebrow="Audits" title="New audit" sub="Websites are checked in the background, two at a time, politely and within a time limit each." />
      {blocked.length > 0 && (
        <Banner kind="warn">
          Left out of the audit because {blocked.length === 1 ? "this business is" : "these businesses are"} marked “do not contact”:{" "}
          <strong>{blocked.map((row) => row.name).join(", ")}</strong>.
          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            <Button size="sm" loading={busy} onClick={auditBlocked}>
              Audit {blocked.length === 1 ? "it" : "them"} anyway
            </Button>
            {madeAudit !== null && (
              <Button size="sm" variant="primary" onClick={() => navigate(`/audits/${madeAudit}`)}>
                Go to the audit of the rest
              </Button>
            )}
          </div>
        </Banner>
      )}
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
                {() => (
                  <DropZone
                    accept=".csv,text/csv"
                    onFile={takeCsv}
                    chosen={file?.name ?? null}
                    title="Drop a CSV here, or choose one"
                    hint={file ? `${plural(csvRows, "row")} to audit` : "Straight out of a download folder or a chat window"}
                  />
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
            <div className="review-paste">
              <div className="mini-label">Or do the design review yourself, in the Claude app</div>
              <p className="field-hint">
                No API key and nothing billed. Claude opens each website itself, so it sees the animations and how the page behaves —
                things a screenshot cannot show. The reviews are attached as each website finishes scanning.
              </p>
              <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                <Button
                  size="sm"
                  icon={ClipboardCopy}
                  loading={preparing}
                  disabled={source === "paste" ? urlCount === 0 : !file}
                  onClick={copyReviewPrompt}
                >
                  Copy prompt for the Claude app
                </Button>
              </div>
              {prompt && <TextArea readOnly rows={8} value={prompt} aria-label="Prompt to copy" onFocus={(e) => e.currentTarget.select()} />}
              <DropZone
                accept=".csv,text/csv"
                onFile={takeReviews}
                chosen={reviews ? `${reviews.name} · ${plural(reviews.rows, "review")}` : null}
                title="Drop the CSV Claude answered with, or choose it"
                hint="One row per website: website, score, looks_dated, verdict, strengths, weaknesses"
              />
            </div>
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
