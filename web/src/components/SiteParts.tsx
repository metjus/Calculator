import { ClipboardCopy, SquareTerminal } from "lucide-react";
import { useEffect, useState } from "react";
import { useToast } from "../lib/toast";
import { Button } from "./ui";

/** Thumbnails that open full size in the page itself (the desktop window has no tabs). */
export function Screenshots({ base, names, host, large }: { base: string; names: string[]; host: string; large?: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  return (
    <>
      <div className={large ? "shots shots-large" : "shots"}>
        {names.map((name) => (
          <button key={name} type="button" className={`shot-thumb shot-${name}`} onClick={() => setOpen(name)} aria-label={`Show the ${name} screenshot full size`}>
            <img src={`${base}/${name}`} alt={`${name} screenshot of ${host}`} width={large ? undefined : name === "mobile" ? 90 : 280} loading="lazy" />
            {large && <span className="shot-cap">{name === "mobile" ? "Mobile" : "Desktop"}</span>}
          </button>
        ))}
      </div>
      {open && (
        <div className="lightbox" role="dialog" aria-modal="true" aria-label={`${open} screenshot of ${host}`} onClick={() => setOpen(null)}>
          <img src={`${base}/${open}`} alt={`${open} screenshot of ${host}`} />
          <span className="lightbox-hint">Click anywhere or press Esc to close</span>
        </div>
      )}
    </>
  );
}

export function claudePrompt(host: string): string {
  return (
    `I unzipped a Web Audit export for ${host} into this project. ` +
    "Read the CLAUDE.md in that folder first, then help me fix the problems from its REPORT.md, biggest impact first. " +
    "Before each change, tell me what you will change and why; after it, show me how you verified it."
  );
}

export const exportUrl = (auditId: number, siteId: number) => `/api/audits/${auditId}/sites/${siteId}/claude-export`;

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Clipboard API needs a secure context; fall back to a temporary textarea.
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

/** Download link for one website's Claude Code export plus the prompt to paste. */
export function ClaudeExport({ auditId, siteId, host }: { auditId: number; siteId: number; host: string }) {
  const toast = useToast();
  return (
    <div className="export-box">
      <SquareTerminal size={20} aria-hidden className="export-icon" />
      <div className="export-text">
        <strong>Fix it with Claude Code</strong>
        <span className="muted">
          A ZIP with every problem and its exact place on the page, how to fix and verify it, the page contents, its HTML and screenshots. Unzip it
          into the website's project and paste the prompt into Claude Code.
        </span>
      </div>
      <div className="row" style={{ gap: 8 }}>
        <a className="btn btn-primary btn-sm" href={exportUrl(auditId, siteId)} download>
          Download ZIP
        </a>
        <Button
          size="sm"
          icon={ClipboardCopy}
          onClick={async () => {
            const copied = await copyText(claudePrompt(host));
            toast(copied ? "Prompt copied – paste it into Claude Code" : "Could not copy the prompt", copied ? "ok" : "error");
          }}
        >
          Copy prompt
        </Button>
      </div>
    </div>
  );
}

