import { useEffect, useState, type FormEvent } from "react";
import { Eye, ShieldCheck } from "lucide-react";
import App from "../App";
import { api } from "../api";
import { Button } from "../components/ui";
// The demo login in front of the app. The backend keeps the session in an httpOnly cookie; this only asks /me.
export default function SignIn() {
  const [user, setUser] = useState<string | null | undefined>(undefined); // undefined = still checking
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.me().then(setUser, (e: Error) => {
      setUser(null);
      setError(e.message);
    });
  }, []);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      setUser(await api.login(email, password));
      setPassword("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const signOut = async () => {
    await api.logout().catch(() => undefined); // signed out locally either way
    setUser(null);
  };
  if (user === undefined) return null;
  if (user) return <App onSignOut={signOut} />;
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
        <p className="signin-note">Demo account. Everything stays on this computer.</p>
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
        {error && (
          <p className="signin-error" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" tone="forest" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
        <p className="signin-trust">
          <ShieldCheck size={16} />
          You choose what to share. You have the final say.
        </p>
      </form>
    </main>
  );
}
