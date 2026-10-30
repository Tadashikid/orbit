import { useEffect, useState, type FormEvent } from "react";
import { Eye, ShieldCheck } from "lucide-react";
import App from "../App";
import { api } from "../api";
import { Button } from "../components/ui";
import { googleConfigured, googleError, googleIdToken } from "../firebase";
// Sign-in in front of the app: Google (Firebase) first, the demo password only if it's switched on.
// The backend keeps the session in an httpOnly cookie; this page only asks /me and /auth/config.
export default function SignIn() {
  const [user, setUser] = useState<string | null | undefined>(undefined); // undefined = still checking
  const [ways, setWays] = useState({ google: false, demo: false });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.me().then(setUser, (e: Error) => {
      setUser(null);
      setError(e.message);
    });
    api.authConfig().then(setWays, () => undefined);
  }, []);
  const signedIn = async (attempt: () => Promise<string>) => {
    setBusy(true);
    setError("");
    try {
      setUser(await attempt());
      setPassword("");
    } catch (err) {
      const message = googleError(err);
      if (message) setError(message);
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void signedIn(() => api.login(email, password));
  };
  const withGoogle = () => void signedIn(async () => api.googleLogin(await googleIdToken()));
  const signOut = async () => {
    await api.logout().catch(() => undefined); // signed out locally either way
    setUser(null);
  };
  if (user === undefined) return null;
  if (user) return <App onSignOut={signOut} />;
  const google = ways.google && googleConfigured();
  return (
    <main className="signin">
      <form className="signin-card" onSubmit={submit}>
        <span className="brand">
          <span className="logo-mark">
            <Eye size={25} />
          </span>
          <span>
            ORBIT<span className="brand-period">.</span>
          </span>
        </span>
        <h1>Sign in</h1>
        {google && (
          <>
            <p className="signin-note">Use your Google account. Orbit only sees your name and email.</p>
            <Button type="button" tone="forest" disabled={busy} onClick={withGoogle}>
              {busy ? "Signing in…" : "Continue with Google"}
            </Button>
          </>
        )}
        {ways.demo && (
          <>
            <p className="signin-note">{google ? "Or use the demo account." : "Demo account. Everything stays on this computer."}</p>
            <label>
              Email
              <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label>
              Password
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <Button type="submit" tone={google ? "paper" : "forest"} disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </>
        )}
        {!google && !ways.demo && (
          <p className="signin-note">Sign-in isn't set up yet: add FIREBASE_PROJECT_ID (or a demo password) to .env.</p>
        )}
        {error && (
          <p className="signin-error" role="alert">
            {error}
          </p>
        )}
        <p className="signin-trust">
          <ShieldCheck size={16} />
          You choose what to share. You have the final say.
        </p>
      </form>
    </main>
  );
}
