import {
  Archive,
  ArchiveRestore,
  CalendarClock,
  ChevronRight,
  ExternalLink,
  FileText,
  Eraser,
  Mail,
  MessageSquare,
  Phone,
  Plus,
  Save,
  Trash2,
  TriangleAlert,
  Users,
} from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Banner, Button, Card, Field, PageHeader, ScoreBadge, Spinner, Tag, TextArea, TextInput } from "../components/ui";
import { api, type ContactWay, type CrmStatus, type CustomerCard as Card_, type DuplicateMatch, type TimelineEntry } from "../lib/api";
import { formatDate } from "../lib/format";
import { useToast } from "../lib/toast";
import { useApi } from "../lib/useApi";
import { customerName, STATUS_COLOUR } from "./Customers";

const WAY_LABEL: Record<ContactWay, string> = { in_person: "In person", phone: "Phone", email: "E-mail", message: "Message" };
const WAY_ICON = { in_person: Users, phone: Phone, email: Mail, message: MessageSquare } as const;

export function CustomerCard() {
  const { id } = useParams();
  const card = useApi<Card_>(`/api/companies/${id}`);
  const toast = useToast();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);

  async function call<T>(path: string, options: { method?: string; body?: Record<string, unknown> }, message: string) {
    setBusy(true);
    try {
      card.setData(await api<Card_>(path, options as never));
      toast(message);
      return true as unknown as T;
    } catch (e) {
      toast(e instanceof Error ? e.message : "That did not work", "error");
      return false as unknown as T;
    } finally {
      setBusy(false);
    }
  }

  if (card.error) return <Banner kind="error">{card.error.message}</Banner>;
  if (!card.data) return <Spinner />;
  const { customer, timeline, statuses, ways } = card.data;
  const name = customerName(customer);

  async function remove(keepUrl: boolean) {
    const what = keepUrl
      ? "Delete this customer but keep the address marked “do not contact”?"
      : "Delete this customer completely, including the history? This cannot be undone.";
    if (!window.confirm(what)) return;
    try {
      await api(`/api/companies/${id}?keep_url=${keepUrl}`, { method: "DELETE" });
      toast("Customer deleted");
      navigate("/customers");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not delete the customer", "error");
    }
  }

  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/customers">Customers</Link>
        <ChevronRight size={14} aria-hidden />
        <span aria-current="page">{name}</span>
      </nav>

      <PageHeader
        eyebrow={customer.project ?? "No project"}
        title={name}
        sub={
          customer.has_website ? (
            <a href={customer.url ?? "#"} target="_blank" rel="noreferrer noopener">
              {customer.domain} <ExternalLink size={13} aria-hidden />
            </a>
          ) : (
            "No website yet — a lead for a new one"
          )
        }
        actions={
          <>
            {customer.site_id && (
              <Link to={`/audits/${customer.audit_id}/sites/${customer.site_id}`} className="btn">
                <FileText size={16} aria-hidden /> Open the audit
              </Link>
            )}
            <Button
              icon={customer.archived_at ? ArchiveRestore : Archive}
              onClick={() =>
                call(
                  `/api/companies/${id}/${customer.archived_at ? "unarchive" : "archive"}`,
                  { method: "POST" },
                  customer.archived_at ? "Back among the customers" : "Moved to the archive",
                )
              }
            >
              {customer.archived_at ? "Bring back" : "Archive"}
            </Button>
            <Link to="/audits/new" className="btn btn-primary">
              Audit again
            </Link>
          </>
        }
      />

      {customer.archived_at && (
        <Banner kind="info">
          In the archive since {formatDate(customer.archived_at)}. Nothing has been deleted — press <em>Bring back</em> to work with them
          again.
        </Banner>
      )}
      {customer.do_not_contact && <Banner kind="warn">This customer is marked “do not contact”.</Banner>}
      <Duplicates id={Number(id)} />
      {customer.proposal_warning && (
        <Banner kind="warn">
          <TriangleAlert size={16} aria-hidden /> The design demo has been up for a while — it may be time to take it down.
        </Banner>
      )}

      <div className="grid-card">
        <div className="stack" style={{ gap: 18 }}>
          <Card title="Status" meta={customer.status_at ? `since ${formatDate(customer.status_at)}` : undefined}>
            <div className="status-row">
              {statuses.map((row) => (
                <button
                  key={row.id}
                  type="button"
                  className={`status-pill${row.id === customer.status ? " on" : ""}`}
                  style={{ ["--pill" as string]: STATUS_COLOUR[row.id] }}
                  disabled={busy}
                  onClick={() => void call(`/api/companies/${id}/status`, { method: "POST", body: { status: row.id } }, `Status: ${row.label}`)}
                >
                  <span className="dot" aria-hidden />
                  {row.label}
                </button>
              ))}
            </div>
            {customer.status === "deal" && <DealValue id={Number(id)} value={customer.deal_value} onSaved={card.setData} />}
          </Card>

          <LogContact id={Number(id)} ways={ways} onSaved={card.setData} />

          <Card title="Timeline" meta={`${timeline.length} entries`}>
            {timeline.length === 0 ? (
              <p className="muted">Nothing has happened yet.</p>
            ) : (
              <ol className="timeline">
                {timeline.map((entry) => (
                  <Entry
                    key={`${entry.kind}-${entry.id}`}
                    entry={entry}
                    onDelete={
                      entry.kind === "audit"
                        ? undefined
                        : () => void call(`/api/companies/${id}/events/${entry.id}`, { method: "DELETE" }, "Entry removed")
                    }
                  />
                ))}
              </ol>
            )}
          </Card>
        </div>

        <div className="stack" style={{ gap: 18 }}>
          <Details customer={customer} onSaved={card.setData} />
          <Card title="Danger zone">
            <div className="stack" style={{ gap: 10 }}>
              <Button
                icon={Trash2}
                onClick={() => void call(`/api/companies/${id}/notes`, { method: "DELETE" }, "Notes deleted")}
                title="Keeps the business, the website, the dates and the audit results"
              >
                Delete notes
              </Button>
              <Button icon={Trash2} onClick={() => void remove(true)}>
                Delete, keep the address
              </Button>
              <Button icon={Trash2} onClick={() => void remove(false)}>
                Delete completely
              </Button>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}

function Entry({ entry, onDelete }: { entry: TimelineEntry; onDelete?: () => void }) {
  const Icon =
    entry.kind === "contact"
      ? WAY_ICON[entry.way ?? "message"]
      : entry.kind === "audit"
        ? FileText
        : entry.kind === "archived"
          ? Archive
          : entry.kind === "unarchived"
            ? ArchiveRestore
            : entry.kind === "notes_cleared"
              ? Eraser
              : CalendarClock;
  const title =
    entry.kind === "status"
      ? `Status: ${entry.status_label}`
      : entry.kind === "contact"
        ? `Contacted · ${WAY_LABEL[entry.way ?? "message"]}`
        : entry.kind === "proposal"
          ? "Design demo sent"
          : entry.kind === "archived"
            ? "Moved to the archive"
            : entry.kind === "unarchived"
              ? "Brought back from the archive"
              : entry.kind === "notes_cleared"
                ? "Notes cleared (the business, the website and the results stay)"
                : entry.kind === "audit"
                  ? `Website audited${entry.score !== null && entry.score !== undefined ? ` · ${entry.score}/100` : ` · ${entry.state}`}`
                  : "Note";
  return (
    <li>
      <Icon size={15} aria-hidden />
      <div>
        <span className="cell-main">{title}</span>
        {entry.note && <span className="cell-sub">{entry.note}</span>}
      </div>
      <time dateTime={entry.at ?? undefined}>{formatDate(entry.at)}</time>
      {entry.kind === "audit" && entry.site_id ? (
        <Link to={`/audits/${entry.audit_id}/sites/${entry.site_id}`} className="btn btn-ghost btn-sm">
          Open
        </Link>
      ) : onDelete ? (
        <button type="button" className="icon-btn" onClick={onDelete} aria-label="Remove this entry">
          <Trash2 size={14} aria-hidden />
        </button>
      ) : null}
    </li>
  );
}

/** The brief's duplicate check, on the card this time: who else looks like the same business. */
function Duplicates({ id }: { id: number }) {
  const found = useApi<DuplicateMatch[]>(`/api/companies/${id}/duplicates`);
  const rows = found.data ?? [];
  if (rows.length === 0) return null;
  return (
    <Banner kind="warn">
      This looks like a business you already have:{" "}
      {rows.map((row, index) => (
        <span key={row.id}>
          {index > 0 && ", "}
          <Link to={`/customers/${row.id}`}>{row.name || row.domain || `#${row.id}`}</Link> — {row.status_label}
        </span>
      ))}
      .
    </Banner>
  );
}

function LogContact({ id, ways, onSaved }: { id: number; ways: ContactWay[]; onSaved: (card: Card_) => void }) {
  const [way, setWay] = useState<ContactWay>("phone");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function save() {
    setBusy(true);
    try {
      onSaved(await api<Card_>(`/api/companies/${id}/contacts`, { method: "POST", body: { way, note } }));
      setNote("");
      toast("Contact logged");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not log the contact", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Log a contact" meta="date, how, and a short note — never who">
      <div className="contact-row">
        <select className="select" value={way} onChange={(e) => setWay(e.target.value as ContactWay)} aria-label="How">
          {ways.map((value) => (
            <option key={value} value={value}>
              {WAY_LABEL[value]}
            </option>
          ))}
        </select>
        <TextInput value={note} onChange={(e) => setNote(e.target.value)} placeholder="What was said, in a few words" aria-label="Note" maxLength={2000} />
        <Button icon={Plus} variant="primary" loading={busy} onClick={save}>
          Log
        </Button>
      </div>
    </Card>
  );
}

function DealValue({ id, value, onSaved }: { id: number; value: number | null; onSaved: (card: Card_) => void }) {
  const [amount, setAmount] = useState(value === null ? "" : String(value));
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  return (
    <div className="contact-row" style={{ marginTop: 12 }}>
      <TextInput
        value={amount}
        onChange={(e) => setAmount(e.target.value.replace(/[^\d]/g, ""))}
        placeholder="Agreed price in €"
        aria-label="Agreed price"
        inputMode="numeric"
      />
      <Button
        icon={Save}
        loading={busy}
        onClick={async () => {
          setBusy(true);
          try {
            onSaved(
              await api<Card_>(`/api/companies/${id}/status`, { method: "POST", body: { status: "deal", deal_value: Number(amount || 0) } }),
            );
            toast("Price saved");
          } finally {
            setBusy(false);
          }
        }}
      >
        Save price
      </Button>
    </div>
  );
}

function Details({ customer, onSaved }: { customer: Card_["customer"]; onSaved: (card: Card_) => void }) {
  const [form, setForm] = useState({
    name: customer.name ?? "",
    url: customer.url ?? "",
    project: customer.project ?? "",
    notes: customer.notes ?? "",
    next_step: customer.next_step ?? "",
    next_step_at: customer.next_step_at ? customer.next_step_at.slice(0, 10) : "",
    proposal_url: customer.proposal_url ?? "",
  });
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }));

  async function save() {
    setBusy(true);
    try {
      onSaved(
        await api<Card_>(`/api/companies/${customer.id}`, {
          method: "PATCH",
          body: { ...form, next_step_at: form.next_step_at ? new Date(form.next_step_at).toISOString() : null },
        }),
      );
      toast("Saved");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Details" meta={customer.score !== null ? undefined : "no score yet"}>
      <div className="stack" style={{ gap: 12 }}>
        {customer.score !== null && (
          <div className="row" style={{ gap: 10, alignItems: "center" }}>
            <ScoreBadge score={customer.score} category={null} />
            <span className="muted small">latest audit</span>
          </div>
        )}
        <Field label="Business name">{(fid) => <TextInput id={fid} value={form.name} onChange={set("name")} maxLength={300} />}</Field>
        <Field label="Website" hint="Add one later and the business can be audited like any other.">
          {(fid) => <TextInput id={fid} value={form.url} onChange={set("url")} placeholder="example.sk" />}
        </Field>
        <Field label="Project">{(fid) => <TextInput id={fid} value={form.project} onChange={set("project")} maxLength={200} />}</Field>
        <Field label="Next step" hint="Shows up on the follow-up list on the day it is due.">
          {(fid) => <TextInput id={fid} value={form.next_step} onChange={set("next_step")} maxLength={300} placeholder="Call back, send the proposal…" />}
        </Field>
        <Field label="Next step on">
          {(fid) => <input id={fid} className="input" type="date" value={form.next_step_at} onChange={set("next_step_at")} />}
        </Field>
        <Field label="Design demo" hint="The live preview you sent. The program reminds you to take it down after the time set in Settings.">
          {(fid) => <TextInput id={fid} value={form.proposal_url} onChange={set("proposal_url")} placeholder="https://…" />}
        </Field>
        <Field label="Notes" hint="Only about the business — never a contact person, phone number or e-mail.">
          {(fid) => <TextArea id={fid} rows={4} value={form.notes} onChange={set("notes")} maxLength={5000} />}
        </Field>
        <div className="row">
          <Button variant="primary" icon={Save} loading={busy} onClick={save}>
            Save
          </Button>
          {customer.status && <Tag color={STATUS_COLOUR[customer.status as CrmStatus]}>{customer.status_label}</Tag>}
        </div>
      </div>
    </Card>
  );
}
