import { Compass, RotateCw } from "lucide-react";
import { Component, type ReactNode } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Shell } from "./components/Shell";
import { Banner, Button, EmptyState, Spinner } from "./components/ui";
import { SessionProvider, useSession } from "./lib/session";
import { ThemeProvider } from "./lib/theme";
import { ToastProvider } from "./lib/toast";
import { AuditRun } from "./pages/AuditRun";
import { Audits } from "./pages/Audits";
import { AuthPage } from "./pages/AuthPage";
import { CustomerCard } from "./pages/CustomerCard";
import { Customers } from "./pages/Customers";
import { Dashboard } from "./pages/Dashboard";
import { NewAudit } from "./pages/NewAudit";
import { Search } from "./pages/Search";
import { Settings } from "./pages/Settings";
import { PdfReport } from "./pages/PdfReport";
import { SiteDetail } from "./pages/SiteDetail";

/** Keeps the shell usable when one page crashes, instead of a blank window. */
class PageBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="stack">
        <Banner kind="error">Something went wrong on this page. Your data is safe; reloading usually helps.</Banner>
        <div>
          <Button icon={RotateCw} onClick={() => window.location.reload()}>
            Reload page
          </Button>
        </div>
      </div>
    );
  }
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading } = useSession();
  const location = useLocation();
  if (loading) {
    return (
      <div className="auth">
        <Spinner />
      </div>
    );
  }
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return (
    <Shell>
      <PageBoundary key={location.pathname}>{children}</PageBoundary>
    </Shell>
  );
}

function GuestOnly({ children }: { children: ReactNode }) {
  const { me, loading } = useSession();
  if (loading) return null;
  return me ? <Navigate to="/" replace /> : <>{children}</>;
}

function NotFound() {
  return (
    <EmptyState
      icon={Compass}
      title="Page not found"
      action={
        <Link to="/" className="btn btn-primary">
          Go to dashboard
        </Link>
      }
    >
      The address may be mistyped, or the page was moved.
    </EmptyState>
  );
}

const PAGES: [string, ReactNode][] = [
  ["/", <Dashboard />],
  ["/search", <Search />],
  ["/audits", <Audits />],
  ["/audits/new", <NewAudit />],
  ["/audits/:id", <AuditRun />],
  ["/audits/:auditId/sites/:siteId", <SiteDetail />],
  ["/audits/:auditId/sites/:siteId/pdf", <PdfReport />],
  ["/customers", <Customers />],
  ["/customers/:id", <CustomerCard />],
  ["/settings", <Settings />],
  ["*", <NotFound />],
];

export function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <SessionProvider>
          <BrowserRouter>
            <Routes>
              <Route
                path="/login"
                element={
                  <GuestOnly>
                    <AuthPage mode="login" />
                  </GuestOnly>
                }
              />
              <Route
                path="/signup"
                element={
                  <GuestOnly>
                    <AuthPage mode="signup" />
                  </GuestOnly>
                }
              />
              {PAGES.map(([path, page]) => (
                <Route key={path} path={path} element={<RequireAuth>{page}</RequireAuth>} />
              ))}
            </Routes>
          </BrowserRouter>
        </SessionProvider>
      </ToastProvider>
    </ThemeProvider>
  );
}
