import { ArrowDown, ArrowUp, Check, Download, FileDown, Settings2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Banner, Button, Card, Field, PageHeader, Spinner, TextArea, TextInput } from "../components/ui";
import { apiRaw, type OfferOption, type PdfChoices, type PdfPreview } from "../lib/api";
import { useToast } from "../lib/toast";
import { useApi } from "../lib/useApi";

const LANGUAGE_NAME: Record<string, string> = { sk: "Slovenčina", cs: "Čeština", en: "English" };
const PAGE_WIDTH = 794; // 210 mm at 96 dpi — the width the report is laid out in
const PAGE_HEIGHT = 1123;
const REDRAW_MS = 400; // the preview is HTML, so a redraw costs milliseconds

type Row = { id: string; included: boolean };

/** Everything the operator decides before the export; the preview redraws from exactly this. */
function choicesOf(preview: PdfPreview, rows: Row[], clientName: string, summary: string, offer: OfferOption[]): PdfChoices {
  return {
    language: preview.language,
    client_name: clientName.trim() || null,
    summary,
    include: rows.filter((row) => row.included).map((row) => row.id),
    offer,
  };
}

export function PdfReport() {
  const { auditId, siteId } = useParams();
  const toast = useToast();
  const [language, setLanguage] = useState<string | null>(null);
  const base = `/api/audits/${auditId}/sites/${siteId}`;
  const preview = useApi<PdfPreview>(`${base}/pdf-preview${language ? `?lang=${language}` : ""}`);

  const [rows, setRows] = useState<Row[]>([]);
  const [clientName, setClientName] = useState("");
  const [summary, setSummary] = useState("");
  const [offer, setOffer] = useState<OfferOption[]>([]);
  const [exporting, setExporting] = useState(false);

  const data = preview.data;
  useEffect(() => {
    if (!data) return;
    setRows(data.issues.map((issue) => ({ id: issue.id, included: true })));
    setClientName(data.client_name ?? "");
    setSummary(data.summary);
    setOffer(data.offer);
  }, [data]);

  const labels = useMemo(() => new Map((data?.issues ?? []).map((issue) => [issue.id, issue])), [data]);
  const choices = data ? choicesOf(data, rows, clientName, summary, offer) : null;
  const included = rows.filter((row) => row.included).length;

  function move(index: number, by: number) {
    setRows((current) => {
      const next = [...current];
      const target = index + by;
      if (target < 0 || target >= next.length) return current;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function editOption(index: number, patch: Partial<OfferOption>) {
    setOffer((current) => current.map((option, i) => (i === index ? { ...option, ...patch } : option)));
  }

  function recommend(index: number) {
    setOffer((current) => current.map((option, i) => ({ ...option, recommended: i === index })));
  }

  async function exportPdf() {
    if (!choices || !data) return;
    setExporting(true);
    try {
      const response = await apiRaw(`${base}/pdf`, choices);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = data.file_name;
      link.click();
      URL.revokeObjectURL(url);
      toast("PDF saved");
    } catch (e) {
      toast(e instanceof Error ? e.message : "The PDF could not be created", "error");
    } finally {
      setExporting(false);
    }
  }

  if (preview.error) return <Banner kind="error">{preview.error.message}</Banner>;
  if (!data || !choices) return <Spinner />;

  return (
    <>
      <PageHeader
        eyebrow={<Link to={`/audits/${auditId}/sites/${siteId}`}>← Back to the website</Link>}
        title="Client PDF"
        sub={`${data.profile.name || "Add your details in Settings"} · ${plural(included, "problem")} in the report`}
        actions={
          <Button variant="primary" icon={FileDown} loading={exporting} onClick={exportPdf}>
            Export PDF
          </Button>
        }
      />

      {!data.profile.name && (
        <Banner kind="warn">
          Your name, company ID and contact are printed on the report and go into the QR code. Add them in{" "}
          <Link to="/settings">Settings</Link>.
        </Banner>
      )}

      <div className="pdf-cols">
        <div className="stack" style={{ gap: 18 }}>
          <Card title="Report" meta="what the client sees first">
            <div className="stack" style={{ gap: 14 }}>
              <div className="pdf-row">
                <div>
                  <span className="pdf-label">Language</span>
                  <div className="seg" role="group" aria-label="Report language">
                    {data.languages.map((code) => (
                      <button
                        key={code}
                        type="button"
                        className={code === data.language ? "on" : ""}
                        aria-pressed={code === data.language}
                        onClick={() => setLanguage(code)}
                      >
                        {LANGUAGE_NAME[code] ?? code}
                      </button>
                    ))}
                  </div>
                </div>
                <Field label="Business name on the cover" hint="Printed in the header. Left empty, the domain is used.">
                  {(id, describedBy) => (
                    <TextInput
                      id={id}
                      aria-describedby={describedBy}
                      value={clientName}
                      placeholder={data.file_name.replace(/^audit-|\.pdf$/g, "")}
                      onChange={(e) => setClientName(e.target.value)}
                      maxLength={200}
                    />
                  )}
                </Field>
              </div>
              <Field label="Opening paragraph" hint="Prefilled — rewrite it in your own words if you like.">
                {(id, describedBy) => (
                  <TextArea id={id} aria-describedby={describedBy} rows={4} value={summary} onChange={(e) => setSummary(e.target.value)} maxLength={1500} />
                )}
              </Field>
            </div>
          </Card>

          <Card title="Problems in the report" meta={`${included} of ${rows.length} included · order with ↑ ↓`}>
            {rows.length === 0 ? (
              <p className="muted">This website has no problems to report.</p>
            ) : (
              <ul className="pdf-issues">
                {rows.map((row, index) => {
                  const issue = labels.get(row.id);
                  if (!issue) return null;
                  return (
                    <li key={row.id} className={row.included ? "" : "off"}>
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={row.included}
                          onChange={(e) =>
                            setRows((current) => current.map((r, i) => (i === index ? { ...r, included: e.target.checked } : r)))
                          }
                        />
                        <span>
                          <span className="cell-main">{issue.label}</span>
                          <span className="cell-sub">{issue.problem}</span>
                        </span>
                      </label>
                      <div className="pdf-move">
                        <span className="tag" style={{ ["--dot" as string]: issue.status === "fail" ? "var(--crit)" : "var(--ok)" }}>
                          <span className="dot" aria-hidden />
                          {issue.status === "fail" ? "Important" : "Minor"}
                        </span>
                        <button type="button" className="icon-btn" onClick={() => move(index, -1)} disabled={index === 0} aria-label="Move up">
                          <ArrowUp size={15} aria-hidden />
                        </button>
                        <button
                          type="button"
                          className="icon-btn"
                          onClick={() => move(index, 1)}
                          disabled={index === rows.length - 1}
                          aria-label="Move down"
                        >
                          <ArrowDown size={15} aria-hidden />
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>

          <Card title="Offer" meta="your prices · never itemised in the PDF">
            <div className="stack" style={{ gap: 10 }}>
              {offer.map((option, index) => (
                <div key={index} className={`pdf-offer${option.recommended ? " pick" : ""}`}>
                  <label className="check pdf-pick">
                    <input type="radio" name="recommended" checked={option.recommended} onChange={() => recommend(index)} />
                    <span className="pdf-label">
                      Option {index + 1}
                      {option.recommended ? " · marked “Recommended”" : ""}
                    </span>
                  </label>
                  <div className="pdf-offer-grid">
                    <TextInput
                      value={option.title}
                      aria-label={`Option ${index + 1} title`}
                      onChange={(e) => editOption(index, { title: e.target.value })}
                    />
                    <TextInput
                      value={option.price}
                      aria-label={`Option ${index + 1} price`}
                      placeholder="e.g. 180 €"
                      onChange={(e) => editOption(index, { price: e.target.value })}
                    />
                  </div>
                  <TextArea
                    rows={2}
                    aria-label={`Option ${index + 1} description`}
                    value={option.description}
                    onChange={(e) => editOption(index, { description: e.target.value })}
                  />
                </div>
              ))}
              <span className="field-hint">Saved as your defaults — the next export starts with these prices.</span>
            </div>
          </Card>
        </div>

        <Preview base={base} choices={choices} hasLogo={data.has_logo} />
      </div>
    </>
  );
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** The real report, drawn from the same HTML the PDF is made of, scaled to fit the column. */
function Preview({ base, choices, hasLogo }: { base: string; choices: PdfChoices; hasLogo: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [pages, setPages] = useState(1);
  const [busy, setBusy] = useState(true);
  const [problem, setProblem] = useState<string | null>(null);
  const [width, setWidth] = useState(PAGE_WIDTH);

  const draw = useCallback(async () => {
    setBusy(true);
    try {
      const html = await (await apiRaw(`${base}/pdf-html`, choices)).text();
      setPages(Math.max(1, html.split('class="page"').length - 1));
      setUrl((old) => {
        if (old) URL.revokeObjectURL(old);
        return URL.createObjectURL(new Blob([html], { type: "text/html" }));
      });
      setProblem(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The preview could not be drawn");
    } finally {
      setBusy(false);
    }
  }, [base, JSON.stringify(choices)]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const timer = window.setTimeout(() => void draw(), REDRAW_MS);
    return () => window.clearTimeout(timer);
  }, [draw]);

  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.observe(element);
    setWidth(element.clientWidth);
    return () => observer.disconnect();
  }, []);

  const scale = Math.min(1, width / PAGE_WIDTH);
  return (
    <Card title="Preview" meta={busy ? "drawing…" : `${pages} page${pages === 1 ? "" : "s"}`} className="pdf-preview">
      {problem && <Banner kind="warn">{problem}</Banner>}
      <div className="pdf-paper" ref={box}>
        <div style={{ width: PAGE_WIDTH * scale, height: PAGE_HEIGHT * pages * scale }}>
          {url && (
            <iframe
              title="Report preview"
              src={url}
              sandbox=""
              scrolling="no"
              style={{
                width: PAGE_WIDTH,
                height: PAGE_HEIGHT * pages,
                border: 0,
                transform: `scale(${scale})`,
                transformOrigin: "top left",
                display: "block",
              }}
            />
          )}
        </div>
      </div>
      <p className="field-hint pdf-foot">
        <Settings2 size={14} aria-hidden /> Your details{hasLogo ? ", logo" : ""} and the QR code come from{" "}
        <Link to="/settings">Settings</Link>.{" "}
        {hasLogo ? (
          <>
            <Check size={14} aria-hidden /> Logo in use.
          </>
        ) : (
          "Upload a logo there to print it in the header."
        )}
      </p>
      <a className="btn btn-sm pdf-open" href={url ?? "#"} target="_blank" rel="noreferrer noopener">
        <Download size={15} aria-hidden /> Open the preview in a window
      </a>
    </Card>
  );
}
