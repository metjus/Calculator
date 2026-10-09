import { Eye, EyeOff, FlaskConical, FolderOpen, Save, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Banner, Button, Card, Field, PageHeader, Select, Spinner, Tag, TextInput } from "../components/ui";
import { api, type CrmRules, type KeyState, type Profile, type SettingsData } from "../lib/api";
import { formatDate } from "../lib/format";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { useApi } from "../lib/useApi";

type Service = KeyState["service"];

const SERVICES: { service: Service; label: string; guide: string; guideLabel: string; use: string }[] = [
  {
    service: "pagespeed",
    label: "Google PageSpeed API key",
    guide: "https://developers.google.com/speed/docs/insights/v5/get-started",
    guideLabel: "How to get a PageSpeed key",
    use: "Speed scores and Core Web Vitals from Google. Without it, speed is estimated from the page itself.",
  },
  {
    service: "claude",
    label: "Claude API key",
    guide: "https://console.anthropic.com/settings/keys",
    guideLabel: "Create a key in the Anthropic Console",
    use: "Claude reviews the design from the desktop and mobile screenshots: tick “Evaluate design with Claude” on a new audit, or review one website from its detail page. Billed to your Claude account (about $0.03–0.09 per website). Without it, the score is calculated without the design review.",
  },
  {
    service: "google_places",
    label: "Google Places API key",
    guide: "https://developers.google.com/maps/documentation/places/web-service/get-api-key",
    guideLabel: "How to get a Places key",
    use: "Business search on Google Maps. Can be the same Google Cloud key as PageSpeed if both APIs are enabled. Without it, only OpenStreetMap is searched.",
  },
];

function keyStatus(state: KeyState): { label: string; color: string } {
  if (!state.configured) return { label: "Not set", color: "var(--neutral)" };
  if (state.test_ok === true) return { label: "Valid", color: "var(--success)" };
  if (state.test_ok === false) return { label: "Not valid", color: "var(--danger)" };
  return { label: "Saved, not tested", color: "var(--warning)" };
}

function KeyRow({ meta, state, onChange }: { meta: (typeof SERVICES)[number]; state: KeyState; onChange: (s: KeyState) => void }) {
  const toast = useToast();
  const [value, setValue] = useState("");
  const [reveal, setReveal] = useState(false);
  const [busy, setBusy] = useState<"save" | "test" | "remove" | null>(null);
  const status = keyStatus(state);

  async function call(kind: "save" | "test" | "remove") {
    setBusy(kind);
    try {
      const next =
        kind === "test"
          ? await api<KeyState>(`/api/settings/keys/${meta.service}/test`, { method: "POST" })
          : await api<KeyState>(`/api/settings/keys/${meta.service}`, { method: "PUT", body: { key: kind === "save" ? value : "" } });
      onChange(next);
      if (kind === "save") {
        setValue("");
        setReveal(false);
        toast("Key saved. Test it to make sure it works.");
      } else if (kind === "remove") {
        toast("Key removed");
      } else if (next.test_ok) {
        toast("The key works");
      } else {
        toast(next.test_message ?? "The key does not work", "error");
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "Something went wrong", "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <form
      className="key-row"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        if (value.trim()) void call("save");
      }}
    >
      <Field
        label={meta.label}
        hint={
          <>
            {meta.use}{" "}
            <a href={meta.guide} target="_blank" rel="noreferrer">
              {meta.guideLabel}
            </a>
          </>
        }
      >
        {(id, describedBy) => (
          <div className="input-group">
            <TextInput
              id={id}
              aria-describedby={describedBy}
              type={reveal ? "text" : "password"}
              autoComplete="off"
              spellCheck={false}
              placeholder={state.configured ? `•••• •••• ${state.last4 ?? ""}  (saved – type to replace)` : "Paste the key"}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
            <Button
              icon={reveal ? EyeOff : Eye}
              aria-label={reveal ? "Hide key" : "Show key"}
              aria-pressed={reveal}
              onClick={() => setReveal((r) => !r)}
              disabled={!value}
            />
          </div>
        )}
      </Field>
      <div className="row">
        <Button type="submit" variant="primary" icon={Save} loading={busy === "save"} disabled={!value.trim() || busy !== null}>
          Save
        </Button>
        <Button icon={FlaskConical} onClick={() => void call("test")} loading={busy === "test"} disabled={!state.configured || busy !== null}>
          Test key
        </Button>
        {state.configured && (
          <Button variant="ghost" icon={Trash2} onClick={() => void call("remove")} loading={busy === "remove"} disabled={busy !== null}>
            Remove
          </Button>
        )}
        <span className="spacer" />
        <span className="row" style={{ gap: 8 }}>
          <Tag color={status.color}>{status.label}</Tag>
          {state.tested_at && <span className="muted num">{formatDate(state.tested_at)}</span>}
        </span>
      </div>
      {state.test_ok === false && state.test_message && <Banner kind="error">{state.test_message}</Banner>}
    </form>
  );
}

function ProfileForm({ initial, language, onSaved }: { initial: Profile; language: SettingsData["pdf_language"]; onSaved: (s: SettingsData) => void }) {
  const toast = useToast();
  const [profile, setProfile] = useState(initial);
  const [pdfLanguage, setPdfLanguage] = useState(language);
  const [busy, setBusy] = useState(false);
  useEffect(() => setProfile(initial), [initial]);
  const set = (key: keyof Profile) => (e: { target: { value: string } }) => setProfile((p) => ({ ...p, [key]: e.target.value }));

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      onSaved(await api<SettingsData>("/api/settings/profile", { method: "PUT", body: { ...profile, pdf_language: pdfLanguage } }));
      toast("Details saved");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack" onSubmit={save}>
      <div className="form-grid">
        <Field label="Your name">{(id) => <TextInput id={id} autoComplete="name" value={profile.name} onChange={set("name")} maxLength={200} />}</Field>
        <Field label="Company ID (IČO)">{(id) => <TextInput id={id} value={profile.company_id} onChange={set("company_id")} maxLength={40} />}</Field>
        <Field label="Phone">{(id) => <TextInput id={id} type="tel" autoComplete="tel" value={profile.phone} onChange={set("phone")} maxLength={40} />}</Field>
        <Field label="E-mail">{(id) => <TextInput id={id} type="email" autoComplete="email" value={profile.email} onChange={set("email")} maxLength={320} />}</Field>
        <Field label="Default PDF language">
          {(id) => (
            <Select id={id} value={pdfLanguage} onChange={(e) => setPdfLanguage(e.target.value as SettingsData["pdf_language"])}>
              <option value="sk">Slovak</option>
              <option value="cs">Czech</option>
              <option value="en">English</option>
            </Select>
          )}
        </Field>
      </div>
      <div className="row">
        <Button type="submit" variant="primary" icon={Save} loading={busy}>
          Save details
        </Button>
        <span className="muted">These are your own details for the PDF footer. A logo upload comes with the PDF export.</span>
      </div>
    </form>
  );
}

/** Where the program keeps everything, and how to point it somewhere else (desktop only).
 *
 * Choosing a folder never moves the data: the program is running out of that database. The
 * new folder is used on the next start, and the owner copies the old one across if they want
 * their audits with them — the brief's "one folder you can move to another computer".
 */
function DataFolder() {
  const toast = useToast();
  const folder = useApi<{ path: string; pending: string | null }>("/api/local/data-folder");
  const [chosen, setChosen] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setChosen(folder.data?.pending ?? ""), [folder.data]);
  if (folder.error || !folder.data) return folder.loading ? <Spinner /> : null;

  async function act(what: "open" | "save" | "reset") {
    setBusy(true);
    try {
      if (what === "open") {
        await api("/api/local/data-folder/open", { method: "POST" });
      } else {
        await api("/api/local/data-folder", { method: "PUT", body: { path: what === "reset" ? "" : chosen } });
        toast(what === "reset" ? "Back to the folder beside the program" : "The program will use the new folder after a restart");
        void folder.reload();
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "That did not work", "error");
    } finally {
      setBusy(false);
    }
  }

  const pending = folder.data.pending;
  return (
    <div className="stack">
      <Field label="Data folder in use" hint="Database, screenshots, PDFs and the backups made at every start.">
        {(id) => <TextInput id={id} value={folder.data!.path} readOnly />}
      </Field>
      <div className="row" style={{ gap: 8 }}>
        <Button icon={FolderOpen} loading={busy} onClick={() => act("open")}>
          Open data folder
        </Button>
      </div>
      <Field label="Use a different folder from the next start" hint="Nothing is moved. Copy the old folder there yourself to keep your audits.">
        {(id) => <TextInput id={id} value={chosen} onChange={(e) => setChosen(e.target.value)} placeholder="D:\WebAudit\data" />}
      </Field>
      <div className="row" style={{ gap: 8 }}>
        <Button variant="primary" icon={Save} loading={busy} onClick={() => act("save")} disabled={!chosen.trim()}>
          Save location
        </Button>
        {pending && (
          <Button loading={busy} onClick={() => act("reset")}>
            Back to the default
          </Button>
        )}
      </div>
      {pending && <Banner kind="warn">After the next start the program will use {pending}.</Banner>}
    </div>
  );
}

/** The contact card the PDF prints, at a size a phone can actually read off the screen.
 *
 * In the report it is 36 mm and scans off paper; in the PDF preview the whole page is scaled
 * down to the column, so the code lands at about 75 px — too small for any camera. This is
 * where the owner checks their own card works, without exporting a PDF first.
 */
function VcardQr({ profile, saved }: { profile: Profile; saved: number }) {
  const filled = Boolean(profile.name || profile.phone || profile.email);
  if (!filled) return <p className="field-hint">Fill in your details above and the contact code appears here.</p>;
  return (
    <div className="qr-box">
      <img src={`/api/settings/vcard-qr?v=${saved}`} alt="Your contact card as a QR code" width={220} height={220} />
      <div>
        <p className="field-hint">
          Scan this with your phone — it should offer to save {profile.name || "your"} contact with the phone number and e-mail above.
        </p>
        <p className="field-hint">
          The client PDF prints the same code at 36 mm, big enough to scan off paper. In the PDF preview the whole page is shrunk to fit
          the column, so the code there is only a thumbnail — don’t try to scan that one.
        </p>
      </div>
    </div>
  );
}

/** How long each step of the funnel waits before the program says something (stage 8). */
function RulesForm({ initial, onSaved }: { initial: CrmRules; onSaved: (s: SettingsData) => void }) {
  const toast = useToast();
  const [rules, setRules] = useState(initial);
  const [busy, setBusy] = useState(false);
  useEffect(() => setRules(initial), [initial]);
  const set = (key: keyof CrmRules) => (e: { target: { value: string } }) =>
    setRules((current) => ({ ...current, [key]: Number(e.target.value) || 0 }));

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      onSaved(await api<SettingsData>("/api/settings/crm-rules", { method: "PUT", body: { ...rules } }));
      toast("Rules saved");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save", "error");
    } finally {
      setBusy(false);
    }
  }

  const number = (key: keyof CrmRules, max: number) => (id: string) => (
    <TextInput id={id} type="number" min={1} max={max} value={String(rules[key])} onChange={set(key)} />
  );
  return (
    <form className="stack" onSubmit={save}>
      <div className="form-grid">
        <Field label="Follow up after (days)" hint="“Waiting for an answer” longer than this needs a nudge.">
          {number("waiting_days", 120)}
        </Field>
        <Field label="Take the design demo down after (days)">{number("proposal_days", 365)}</Field>
        <Field label="Move to the archive after (months)" hint="Counted from the last step of a finished customer.">
          {number("archive_after_months", 60)}
        </Field>
        <Field label="Offer again after (months)" hint="How long a rejection stays fresh.">
          {number("recontact_after_months", 120)}
        </Field>
        <Field label="Clear notes after (years in the archive)" hint="You are asked first; nothing is ever cleared on its own.">
          {number("clear_notes_after_years", 20)}
        </Field>
      </div>
      <div className="row">
        <Button type="submit" variant="primary" icon={Save} loading={busy}>
          Save rules
        </Button>
        <span className="muted">No customer is ever deleted automatically — the archive only moves them aside.</span>
      </div>
    </form>
  );
}

/** The logo printed in the PDF header. Kept in the data folder, not in the database. */
function LogoRow({ saved, onSaved }: { saved: boolean; onSaved: (s: SettingsData) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    const body = new FormData();
    body.append("file", file);
    setBusy(true);
    try {
      onSaved(await api<SettingsData>("/api/settings/logo", { method: "PUT", body }));
      setVersion((v) => v + 1);
      toast("Logo saved");
    } catch (e) {
      toast(e instanceof Error ? e.message : "The logo could not be saved", "error");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  async function remove() {
    setBusy(true);
    try {
      onSaved(await api<SettingsData>("/api/settings/logo", { method: "DELETE" }));
      toast("Logo removed");
    } catch (e) {
      toast(e instanceof Error ? e.message : "The logo could not be removed", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="logo-box">
        {saved ? (
          <img src={`/api/settings/logo?v=${version}`} alt="Your logo" />
        ) : (
          <span className="muted">No logo yet — the header shows your name instead.</span>
        )}
        <div className="row" style={{ gap: 8 }}>
          <Button icon={Upload} loading={busy} onClick={() => input.current?.click()}>
            {saved ? "Replace" : "Upload"}
          </Button>
          {saved && (
            <Button icon={Trash2} loading={busy} onClick={remove}>
              Remove
            </Button>
          )}
        </div>
      </div>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/svg+xml,image/webp"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void upload(file);
        }}
      />
      <span className="field-hint">PNG, JPEG, SVG or WebP, up to 1 MB. It is printed at about 14 mm tall, so a wide logo works best.</span>
    </div>
  );
}

export function Settings() {
  const settings = useApi<SettingsData>("/api/settings");
  const { data, setData } = settings;
  // Saving the details redraws the code, so the image is not served from the browser cache.
  const [qrVersion, setQrVersion] = useState(0);
  const { me } = useSession();  // the Files card is the desktop program's, not a server's

  return (
    <>
      <PageHeader eyebrow="Workspace" title="Settings" sub="Keys are stored encrypted for this workspace and are never shown again in full." />
      {settings.error && <Banner kind="error">{settings.error.message}</Banner>}
      {!data ? (
        settings.loading && <Spinner />
      ) : (
        <div className="grid-2" style={{ alignItems: "start" }}>
          <Card title="API keys" id="keys">
            <div className="key-list">
              {SERVICES.map((meta) => (
                <KeyRow
                  key={meta.service}
                  meta={meta}
                  state={data.keys[meta.service]}
                  onChange={(next) => setData((d) => (d ? { ...d, keys: { ...d.keys, [meta.service]: next } } : d))}
                />
              ))}
            </div>
          </Card>
          <div className="stack" style={{ gap: 18 }}>
            <Card title="Your details for PDF reports" id="profile">
              <ProfileForm
                initial={data.profile}
                language={data.pdf_language}
                onSaved={(next) => {
                  setData(next);
                  setQrVersion((value) => value + 1);
                }}
              />
            </Card>
            <Card title="Your contact code" id="vcard" meta="the QR printed on the last page of the PDF">
              <VcardQr profile={data.profile} saved={qrVersion} />
            </Card>
            <Card title="Logo" id="logo" meta="printed in the header of the client PDF">
              <LogoRow saved={data.logo} onSaved={setData} />
            </Card>
            <Card title="Reminders and the archive" id="rules" meta="your own numbers behind every rule">
              <RulesForm initial={data.crm_rules} onSaved={setData} />
            </Card>
            {me?.local && (
              <Card title="Files" id="files" meta="everything the program keeps, in one folder">
                <DataFolder />
              </Card>
            )}
          </div>
        </div>
      )}
    </>
  );
}
