/// <reference types="vite/client" />
// Sign-in in the browser (Firebase Auth: Google, or email + password). It only proves who you are: the backend checks
// the token with Google and keeps the session in its own httpOnly cookie. Firebase keeps nothing here: in-memory
// only, signed out at once. Config comes from frontend/.env.local (public identifiers, not secrets).
const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY as string | undefined,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined,
  appId: import.meta.env.VITE_FIREBASE_APP_ID as string | undefined,
};
export const googleConfigured = () => Boolean(config.apiKey && config.authDomain && config.projectId);
// Loads Firebase only when you sign in or up, then hands `use` a fresh in-memory session and signs it out after:
// Orbit's cookie is the only session.
async function firebase<T>(use: (auth: typeof import("firebase/auth"), session: import("firebase/auth").Auth) => Promise<T>) {
  const [{ initializeApp, getApps }, auth] = await Promise.all([import("firebase/app"), import("firebase/auth")]);
  const session = auth.getAuth(getApps()[0] ?? initializeApp(config));
  await auth.setPersistence(session, auth.inMemoryPersistence);
  try {
    return await use(auth, session);
  } finally {
    await auth.signOut(session);
  }
}
// A one-time Google ID token for the backend (signs you up the first time, in after that).
export const googleIdToken = () =>
  firebase(async (auth, session) => {
    const provider = new auth.GoogleAuthProvider();
    provider.setCustomParameters({ prompt: "select_account" }); // pick the account every time
    return (await auth.signInWithPopup(session, provider)).user.getIdToken();
  });
// Email + password: a token only once you've clicked the link in the verification email (the backend checks it too).
export const emailIdToken = (email: string, password: string) =>
  firebase(async (auth, session) => {
    const { user } = await auth.signInWithEmailAndPassword(session, email, password);
    if (!user.emailVerified) {
      await auth.sendEmailVerification(user).catch(() => undefined); // a fresh link; Firebase rate-limits resends
      throw Object.assign(new Error(), { code: "orbit/verify-email", email });
    }
    return user.getIdToken();
  });
// New account: Firebase stores the password (hashed, never here or in Orbit) and emails a verification link.
export const emailSignUp = (email: string, password: string) =>
  firebase(async (auth, session) => {
    const { user } = await auth.createUserWithEmailAndPassword(session, email, password);
    await auth.sendEmailVerification(user);
  });
// Firebase's errors in plain words; null = you closed the Google popup (nothing to say).
export function authError(e: unknown): string | null {
  const { code = "", email = "" } = (e as { code?: string; email?: string }) ?? {};
  if (code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request") return null;
  if (code === "auth/popup-blocked") return "Your browser blocked the Google sign-in window. Allow pop-ups for this site.";
  if (code === "auth/unauthorized-domain")
    return `Firebase doesn't allow sign-in from ${location.hostname} yet. Add it under Authentication › Settings › ` +
      `Authorized domains${location.hostname === "127.0.0.1" ? ", or open localhost instead" : ""}.`;
  if (code === "orbit/verify-email")
    return `Verify your email first: click the link we sent to ${email} (we've just sent a new one), then sign in.`;
  if (["auth/invalid-credential", "auth/wrong-password", "auth/user-not-found"].includes(code)) return "Wrong email or password.";
  if (code === "auth/email-already-in-use") return "There's already an account with this email. Sign in instead.";
  if (code === "auth/weak-password") return "Choose a longer password (at least 8 characters).";
  if (code === "auth/invalid-email") return "That doesn't look like an email address.";
  if (code === "auth/too-many-requests") return "Too many tries. Wait a minute, then try again.";
  if (code === "auth/network-request-failed") return "Can't reach Firebase. Check your internet connection.";
  if (code === "auth/operation-not-allowed")
    return "Email sign-up isn't switched on yet: Firebase › Authentication › Sign-in method › Email/Password.";
  return (e as Error)?.message || "That didn't work. Try again.";
}
