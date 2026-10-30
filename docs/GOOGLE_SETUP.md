# Google + Firebase setup

Everything here is optional: without it Orbit runs on sample data with the demo password login. Each part switches on
by itself once its settings are in `.env` (see [.env.example](../.env.example)). All of it lives in one Google Cloud /
Firebase project (ours: `orbit-8acf7`). **Never paste keys or secrets in chat or commit them.**

| Part | What it gives you | Settings |
|---|---|---|
| 1. Sign-in | Sign up / sign in with Google or email + password | `FIREBASE_PROJECT_ID`, `ORBIT_ALLOWED_EMAILS`, `frontend/.env.local` |
| 2. Firestore | Each account's data in the cloud, locked to the backend | `FIREBASE_SERVICE_ACCOUNT` |
| 3. Connect Google | Orbit reads your real calendar + inbox, read-only | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ORBIT_TOKEN_KEY` |
| 4. Demo data | The demo account's inbox and calendar filled with the persona's data | (uses 3's client) |
| 5. Confirmations | One email (or calendar invitation) per approved booking | `ORBIT_NOTIFY_URL`, `ORBIT_NOTIFY_SECRET` |

## 1. Sign-in (Firebase Auth)

1. https://console.firebase.google.com → your project → **Authentication → Sign-in method**: enable **Google** and
   **Email/Password** (leave "Email link" off).
2. **Authentication → Settings → Authorized domains**: `localhost` is there by default. Open Orbit at
   `http://localhost:4173` (the app moves 127.0.0.1 there itself).
3. **Project settings → General → Your apps → Web app**: copy apiKey, authDomain, projectId and appId into
   `frontend/.env.local` (`VITE_FIREBASE_*`, see `frontend/.env.example`). These identify the project; they aren't secrets.
4. `.env`: `FIREBASE_PROJECT_ID=<projectId>` and `ORBIT_ALLOWED_EMAILS=*` (any verified account) or a comma-separated list.

The backend checks every sign-in token with Google and refuses unverified emails: email sign-ups must click the
verification link first.

## 2. Firestore (per-account data)

1. **Build → Firestore Database → Create database**: Standard edition, location **asia-south1**, production mode.
   Skip scheduled backups (they need the paid plan).
2. **Rules** tab: paste [firestore.rules](../firestore.rules) (deny everything to browsers) → **Publish**.
3. **Project settings → Service accounts → Generate new private key** → save it in the repo root as
   `firebase-service-account.json` (gitignored) → `.env`: `FIREBASE_SERVICE_ACCOUNT=firebase-service-account.json`.

Data lives under `users/{email}/` (conversations, booking cards, the encrypted Google link). Each account's bank
statement stays on the machine running the Finance server (`data/session/statements/`). **Delete my data** removes all
of it, and the sign-in account.

## 3. Connect Google (read-only calendar + inbox)

1. Enable the **Gmail API** and **Google Calendar API** (APIs & Services → Library) in the same project.
2. **Google Auth Platform → Audience**: External. *In production* anyone can connect after Google's "unverified app"
   warning (Advanced → Go to Orbit), up to 100 users; *Testing* limits it to listed test users and expires the link
   after 7 days.
3. **Clients → Create client → Web application**, Authorized redirect URIs:
   `http://localhost:4173/api/google/callback` and `http://localhost:8765/` (the seed script below) → copy the client
   ID and secret into `.env`.
4. `.env`: `ORBIT_TOKEN_KEY` encrypts each account's Google link at rest. Make one with
   `.venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
   Changing it disconnects everyone.
5. Restart the backend → in Orbit click **Connect Google**. Receipts then say `source: live` for Calendar and Gmail.

Only titles and times leave the Calendar server; only emails with a deadline leave Gmail (subject, sender domain, a
short masked snippet). The token travels in each request's metadata, never to the AI.

## 4. Demo data in the demo Google account

```bash
.venv\Scripts\python scripts\seed_demo_google.py
```

Sign in **as the demo account**. It adds the 15 persona emails (original senders and dates) and the 22 calendar
events, once (re-running adds nothing). Don't also import `data/seed/manu_calendar.ics`: that would duplicate the
events. One email is the prompt-injection test on purpose; if Gmail puts it in Spam, mark it **Not spam**.

## 5. Booking confirmations (Google Apps Script)

Follow the steps at the top of [scripts/orbit_notify.gs](../scripts/orbit_notify.gs): new project at
script.google.com → paste the script → Script property `ORBIT_SECRET` = your `ORBIT_NOTIFY_SECRET` → timezone
`Asia/Kolkata` → **Deploy → Web app** (Execute as: Me, Who has access: Anyone) → copy the `/exec` URL into
`ORBIT_NOTIFY_URL`. After changing the script: **Manage deployments → Edit → New version** (keeps the URL).

## Things that will bite you

- **127.0.0.1 vs localhost:** Firebase sign-in and Connect Google only work on `localhost`.
- **`.env` changes need a backend restart**, not just a code reload.
- **"Hey Orbit"** needs Edge if Chrome's speech service is blocked on your network ("network" error).
- **If anything fails, the demo still runs:** sources fall back to sample data and the receipt says `source: seeded`.
