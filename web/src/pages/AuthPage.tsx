import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { BrandMark } from "../components/Shell";
import { Banner, Button, Card, Field, TextInput } from "../components/ui";
import { useSession } from "../lib/session";

export function AuthPage({ mode }: { mode: "login" | "signup" }) {
  const { signIn, signUp } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isSignup = mode === "signup";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (isSignup) await signUp(email, password, workspace);
      else await signIn(email, password);
      const target = (location.state as { from?: string } | null)?.from ?? "/";
      navigate(target, { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <div className="auth-card">
        <div className="auth-brand">
          <BrandMark />
          Web Audit
        </div>
        <Card>
          <form className="stack" onSubmit={submit} noValidate>
            <div>
              <div className="eyebrow">{isSignup ? "Create your workspace" : "Welcome back"}</div>
              <h1 style={{ fontSize: 24, marginTop: 4 }}>{isSignup ? "Sign up" : "Sign in"}</h1>
            </div>
            {error && <Banner kind="error">{error}</Banner>}
            <Field label="E-mail">
              {(id) => <TextInput id={id} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}
            </Field>
            <Field label="Password" hint={isSignup ? "At least 10 characters." : undefined}>
              {(id, describedBy) => (
                <TextInput
                  id={id}
                  type="password"
                  autoComplete={isSignup ? "new-password" : "current-password"}
                  required
                  minLength={isSignup ? 10 : undefined}
                  aria-describedby={describedBy}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              )}
            </Field>
            {isSignup && (
              <Field label="Workspace name" hint="Usually your studio or your own name.">
                {(id, describedBy) => <TextInput id={id} aria-describedby={describedBy} value={workspace} onChange={(e) => setWorkspace(e.target.value)} />}
              </Field>
            )}
            <Button type="submit" variant="primary" loading={busy}>
              {isSignup ? "Create account" : "Sign in"}
            </Button>
          </form>
        </Card>
        <p className="muted" style={{ margin: 0 }}>
          {isSignup ? (
            <>
              Already have an account? <Link to="/login">Sign in</Link>
            </>
          ) : (
            <>
              New here? <Link to="/signup">Create an account</Link>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
