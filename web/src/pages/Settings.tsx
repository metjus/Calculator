import { Eye, EyeOff, FlaskConical, Save, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Banner, Button, Card, Field, PageHeader, Select, Spinner, Tag, TextInput } from "../components/ui";
import { api, type KeyState, type Profile, type SettingsData } from "../lib/api";
import { formatDate } from "../lib/format";
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
    use: "AI review of the design from screenshots (next stage). Without it, the option stays off.",
  },
  {
    service: "google_places",
    label: "Google Places API key",
    guide: "https://developers.google.com/maps/documentation/places/web-service/get-api-key",
    guideLabel: "How to get a Places key",
    use: "Business search on Google Maps. Can be the same Google Cloud key as PageSpeed if both APIs are enabled. Without it, only OpenStreetMap is searched.",
  },
  {
    service: "mapy",
    label: "Mapy.com API key",
    guide: "https://developer.mapy.com/en/how-to-start",
    guideLabel: "How to get a free Mapy.com key",
    use: "Map in Find businesses, from Mapy.com (free monthly allowance). Use it if the OpenStreetMap map does not load. Without it, the map comes from OpenStreetMap.",
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

export function Settings() {
  const settings = useApi<SettingsData>("/api/settings");
  const { data, setData } = settings;

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
          <Card title="Your details for PDF reports" id="profile">
            <ProfileForm initial={data.profile} language={data.pdf_language} onSaved={setData} />
          </Card>
        </div>
      )}
    </>
  );
}
