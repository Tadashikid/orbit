import { useEffect, useState, type FormEvent } from "react";
import { Eye, ShieldCheck } from "lucide-react";
import App from "../App";
import { api } from "../api";
import { Button } from "../components/ui";
import { authError, emailIdToken, emailSignUp, googleConfigured, googleIdToken } from "../firebase";
// In front of the app: Sign in (email + password) and Sign up (Google, or email + password). Accounts live in
// Firebase Auth; the backend checks each token with Google and keeps the session in an httpOnly cookie.
// The demo password (.env) still signs in from the same form, for offline demos.
type Screen = "in" | "up" | "sent";
export default function SignIn() {
  const [user, setUser] = useState<string | null | undefined>(undefined); // undefined = still checking
  const [ways, setWays] = useState({ google: false, demo: false });
  const [screen, setScreen] = useState<Screen>("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState(""); // sign-up only, with the password typed twice
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.me().then(setUser, (e: Error) => {
      setUser(null);
      setError(e.message);
    });
    api.authConfig().then(setWays, () => undefined);
  }, []);
  const accounts = ways.google && googleConfigured(); // Firebase on: Google and email + password accounts
  const go = (next: Screen) => {
    setScreen(next);
    setError("");
    setPassword("");
    setConfirm("");
  };
  const run = async (attempt: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await attempt();
    } catch (err) {
      const message = authError(err);
      if (message) setError(message);
    } finally {
      setBusy(false);
    }
  };
  const signIn = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      try {
        if (!accounts) throw Object.assign(new Error(), { code: "auth/invalid-credential" });
        setUser(await api.googleLogin(await emailIdToken(email, password)));
      } catch (err) {
        // Not a Firebase account: maybe the demo login from .env.
        if (!ways.demo || (err as { code?: string }).code !== "auth/invalid-credential") throw err;
        setUser(await api.login(email, password).catch(() => Promise.reject({ code: "auth/invalid-credential" })));
      }
      setPassword("");
    });
  };
  const signUp = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return setError("Tell us your name.");
    if (password !== confirm) return setError("Passwords don't match.");
    void run(async () => {
      await emailSignUp(name.trim(), email, password);
      go("sent");
    });
  };
  const withGoogle = () => void run(async () => setUser(await api.googleLogin(await googleIdToken())));
  const signOut = async () => {
    await api.logout().catch(() => undefined); // signed out locally either way
    setUser(null);
  };
  if (user === undefined) return null;
  if (user) return <App onSignOut={signOut} />;
  const google = accounts && (
    <Button type="button" tone="forest" className={screen === "up" ? "" : "button-outline"} disabled={busy} onClick={withGoogle}>
      Continue with Google
    </Button>
  );
  const fields = (
    <>
      {screen === "up" && (
        <label>
          Name
          <input type="text" autoComplete="name" required maxLength={60} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
      )}
      <label>
        Email
        <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label>
        Password
        <input
          type="password"
          autoComplete={screen === "up" ? "new-password" : "current-password"}
          required
          minLength={screen === "up" ? 8 : undefined}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      {screen === "up" && (
        <label>
          Confirm password
          <input
            type="password"
            autoComplete="new-password"
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            aria-invalid={confirm !== "" && confirm !== password}
          />
        </label>
      )}
    </>
  );
  return (
    <main className="signin">
      <form className="signin-card" onSubmit={screen === "up" ? signUp : signIn}>
        <span className="brand">
          <span className="logo-mark">
            <Eye size={25} />
          </span>
          <span>
            ORBIT<span className="brand-period">.</span>
          </span>
        </span>
        {screen === "sent" ? (
          <>
            <h1>Check your inbox</h1>
            <p className="signin-note">
              We sent a link to <strong>{email}</strong>. Click it to verify your email, then sign in.
            </p>
            <Button type="button" tone="forest" onClick={() => go("in")}>
              Back to sign in
            </Button>
          </>
        ) : screen === "up" ? (
          <>
            <h1>Sign up</h1>
            {google}
            {accounts ? (
              <>
                <p className="signin-or">or with email</p>
                {fields}
                <Button type="submit" tone="forest" className="button-outline" disabled={busy}>
                  {busy ? "Creating…" : "Create account"}
                </Button>
              </>
            ) : (
              <p className="signin-note">Sign-up isn't set up yet: add the Firebase settings to .env.</p>
            )}
            <p className="signin-switch">
              Already have an account?{" "}
              <button type="button" onClick={() => go("in")}>
                Sign in
              </button>
            </p>
          </>
        ) : (
          <>
            <h1>Sign in</h1>
            {accounts || ways.demo ? (
              <>
                {fields}
                <Button type="submit" tone="forest" disabled={busy}>
                  {busy ? "Signing in…" : "Sign in"}
                </Button>
                {google && (
                  <>
                    <p className="signin-or">or</p>
                    {google}
                  </>
                )}
              </>
            ) : (
              <p className="signin-note">Sign-in isn't set up yet: add FIREBASE_PROJECT_ID (or a demo password) to .env.</p>
            )}
            {accounts && (
              <p className="signin-switch">
                Don't have an account?{" "}
                <button type="button" onClick={() => go("up")}>
                  Sign up
                </button>
              </p>
            )}
          </>
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
