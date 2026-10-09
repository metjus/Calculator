import { CircleAlert, CircleCheck, Info, LoaderCircle, TriangleAlert, Upload, type LucideIcon } from "lucide-react";
import {
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import type { Category } from "../lib/api";
import { CATEGORY_LABEL, CATEGORY_VAR } from "../lib/format";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "md" | "sm";
  icon?: LucideIcon;
  loading?: boolean;
};

export function Button({ variant = "secondary", size = "md", icon: Icon, loading, children, className = "", disabled, ...rest }: ButtonProps) {
  const classes = ["btn", variant !== "secondary" && `btn-${variant}`, size === "sm" && "btn-sm", !children && "btn-icon", className]
    .filter(Boolean)
    .join(" ");
  return (
    <button type="button" className={classes} disabled={disabled || loading} aria-busy={loading || undefined} {...rest}>
      {loading ? <LoaderCircle size={16} className="spin" aria-hidden /> : Icon ? <Icon size={16} aria-hidden /> : null}
      {children}
    </button>
  );
}

export function PageHeader({ eyebrow, title, sub, actions }: { eyebrow?: ReactNode; title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {sub && <p className="page-sub">{sub}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </header>
  );
}

export function Card({ title, meta, children, className = "", id }: { title?: string; meta?: ReactNode; children: ReactNode; className?: string; id?: string }) {
  return (
    <section className={`card ${className}`} id={id} aria-labelledby={title && id ? `${id}-title` : undefined}>
      {title && (
        <div className="card-title">
          <h2 id={id ? `${id}-title` : undefined}>{title}</h2>
          {meta && <span className="meta">{meta}</span>}
        </div>
      )}
      {children}
    </section>
  );
}

type FieldProps = { label: string; hint?: ReactNode; error?: string | null; children: (id: string, describedBy?: string) => ReactNode };

export function Field({ label, hint, error, children }: FieldProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      {children(id, describedBy)}
      {hint && (
        <span className="field-hint" id={hintId}>
          {hint}
        </span>
      )}
      {error && (
        <span className="field-error" id={errorId} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export const TextInput = (props: InputHTMLAttributes<HTMLInputElement>) => <input className="input" {...props} />;
export const Select = (props: SelectHTMLAttributes<HTMLSelectElement>) => <select className="select" {...props} />;
export const TextArea = (props: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea className="textarea" {...props} />;

export function Checkbox({ label, hint, disabled, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode; hint?: ReactNode }) {
  return (
    <div className="field">
      <label className={`check${disabled ? " disabled" : ""}`}>
        <input type="checkbox" disabled={disabled} {...rest} />
        <span>{label}</span>
      </label>
      {hint && <span className="field-hint">{hint}</span>}
    </div>
  );
}

export function ScoreBadge({ score, category }: { score: number | null; category: Category | null }) {
  if (score === null || category === null) return <span className="muted">—</span>;
  return (
    <span className="score" style={{ ["--cat" as string]: CATEGORY_VAR[category] }}>
      <b>{score}</b>
      {CATEGORY_LABEL[category]}
    </span>
  );
}

export function Tag({ color, children }: { color?: string; children: ReactNode }) {
  return (
    <span className="tag">
      <span className="dot" style={color ? { ["--dot" as string]: color } : undefined} aria-hidden />
      {children}
    </span>
  );
}

export function ProgressBar({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="progress" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}>
      <div style={{ width: `${pct}%` }} />
    </div>
  );
}

export function EmptyState({ icon: Icon, title, children, action }: { icon: LucideIcon; title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <Icon size={28} className="empty-icon" aria-hidden />
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </div>
  );
}

const BANNER_ICON = { info: Info, warn: TriangleAlert, error: CircleAlert, success: CircleCheck };

export function Banner({ kind = "info", children }: { kind?: keyof typeof BANNER_ICON; children: ReactNode }) {
  const Icon = BANNER_ICON[kind];
  return (
    <div className={`banner ${kind === "info" ? "" : kind}`} role={kind === "error" ? "alert" : "status"}>
      <Icon size={18} aria-hidden />
      <div>{children}</div>
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span className="row muted" role="status">
      <LoaderCircle size={16} className="spin" aria-hidden /> {label}
    </span>
  );
}

/** A file field you can also drop a file onto — the same control, two ways in.
 *
 * Dropping is the point: the files this takes come straight out of a download folder or a chat
 * window, and a file picker makes that a four-click detour.
 */
export function DropZone({
  accept,
  onFile,
  disabled,
  title,
  hint,
  chosen,
}: {
  accept: string;
  onFile: (file: File) => void;
  disabled?: boolean;
  title: ReactNode;
  hint?: ReactNode;
  chosen?: string | null;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  function take(list: FileList | null) {
    const file = list?.[0];
    if (file && !disabled) onFile(file);
  }

  return (
    <div
      className={`dropzone${over ? " over" : ""}${disabled ? " off" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        take(e.dataTransfer.files);
      }}
    >
      <input
        ref={input}
        type="file"
        accept={accept}
        disabled={disabled}
        className="sr-only"
        onChange={(e) => {
          take(e.target.files);
          e.target.value = "";  // choosing the same file twice still counts
        }}
      />
      <Upload size={18} aria-hidden />
      <div>
        <button type="button" className="link-btn" disabled={disabled} onClick={() => input.current?.click()}>
          {chosen || title}
        </button>
        {hint && <span className="cell-sub">{hint}</span>}
      </div>
    </div>
  );
}
