import { Check, ClipboardCheck, LayoutDashboard, LogOut, Moon, Power, Search, SlidersHorizontal, Sun, Users } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useSession } from "../lib/session";
import { useTheme } from "../lib/theme";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/search", label: "Search", icon: Search },
  { to: "/audits", label: "Audits", icon: ClipboardCheck },
  { to: "/customers", label: "Customers", icon: Users },
  { to: "/settings", label: "Settings", icon: SlidersHorizontal },
];

export function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden>
      <Check size={15} strokeWidth={2.5} />
    </span>
  );
}

export function Shell({ children, followUps = 0 }: { children: ReactNode; followUps?: number }) {
  const { me, signOut } = useSession();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const [closed, setClosed] = useState(false);
  if (closed) {
    return (
      <div className="auth">
        <div className="auth-card" style={{ textAlign: "center" }}>
          <div className="auth-brand" style={{ justifyContent: "center" }}>
            <BrandMark />
            Web Audit
          </div>
          <p>Web Audit has stopped. You can close this window.</p>
        </div>
      </div>
    );
  }
  return (
    <div className="shell">
      <aside className="side">
        <Link to="/" className="brand">
          <BrandMark />
          <span>Web Audit</span>
        </Link>
        <div>
          <div className="nav-label">{me?.workspace_name ?? "Workspace"}</div>
          <nav className="nav" aria-label="Main">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} to={to} end={end}>
                <Icon size={18} aria-hidden />
                {label}
                {to === "/customers" && followUps > 0 && (
                  <span className="badge" aria-label={`${followUps} follow-ups due`}>
                    {followUps}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="side-foot">
          <button type="button" className="side-btn" onClick={toggle}>
            {theme === "dark" ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </button>
          {me?.local ? (
            // Desktop app: one local user, so quitting replaces signing out.
            <button
              type="button"
              className="side-btn"
              onClick={async () => {
                await api("/api/local/quit", { method: "POST" }).catch(() => undefined);
                setClosed(true);
              }}
            >
              <Power size={18} aria-hidden />
              Quit Web Audit
            </button>
          ) : (
            <>
              <button
                type="button"
                className="side-btn"
                onClick={async () => {
                  await signOut();
                  navigate("/login");
                }}
              >
                <LogOut size={18} aria-hidden />
                Sign out
              </button>
              <div className="side-user" title={me?.email}>
                {me?.email}
              </div>
            </>
          )}
        </div>
      </aside>
      <main className="main" id="main">
        {children}
      </main>
    </div>
  );
}
