/// <reference types="vite/client" />
// Google sign-in in the browser (Firebase Auth). It only proves who you are: the backend checks the token with Google
// and keeps the session in its own httpOnly cookie. Firebase keeps nothing here: in-memory only, signed out at once.
// Config comes from frontend/.env.local (public identifiers, not secrets).
const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY as string | undefined,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined,
  appId: import.meta.env.VITE_FIREBASE_APP_ID as string | undefined,
};
export const googleConfigured = () => Boolean(config.apiKey && config.authDomain && config.projectId);
// A one-time Google ID token for the backend. Loads Firebase only when you click the button.
export async function googleIdToken(): Promise<string> {
  const [{ initializeApp, getApps }, auth] = await Promise.all([import("firebase/app"), import("firebase/auth")]);
  const app = getApps()[0] ?? initializeApp(config);
  const session = auth.getAuth(app);
  await auth.setPersistence(session, auth.inMemoryPersistence);
  const provider = new auth.GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" }); // pick the account every time
  try {
    const result = await auth.signInWithPopup(session, provider);
    return await result.user.getIdToken();
  } finally {
    await auth.signOut(session); // Orbit's cookie is the only session
  }
}
// Firebase's popup errors in plain words; null = you closed the popup (nothing to say).
export function googleError(e: unknown): string | null {
  const code = (e as { code?: string })?.code ?? "";
  if (code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request") return null;
  if (code === "auth/popup-blocked") return "Your browser blocked the Google sign-in window. Allow pop-ups for this site.";
  if (code === "auth/unauthorized-domain") return "This address isn't in Firebase's authorized domains.";
  return (e as Error)?.message || "Google sign-in didn't work. Try again.";
}
