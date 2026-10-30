# Orbit

**Everything revolves around your life. Orbit decides with you, and shows its evidence.**

Ask *"Can I afford a Goa trip next weekend?"* or *"Book it"*, by typing or by voice ("Hey Orbit"). Orbit reads your
calendar, email deadlines and bank statement, decides with a deterministic money engine, holds the flights and hotel
for you, and books only when you tap **Approve**. Every answer comes with a receipt of what was read and from where.

- **Agent:** Gemini plans the steps; every tool call goes through **Guardian** (allow-list, approvals, leak guard,
  call budgets, audit log). The AI never does money maths and can never confirm or pay.
- **Sources over MCP:** calendar, Gmail, finance, travel, price and booking servers you switch On/Off per account.
- **Bookings:** Duffel test-mode flights (real API, test balance), sandbox hotels, shopping with a link to the store.
  Approving one sends a confirmation (calendar invitation for flights and stays) via a Google Apps Script.
- **Voice:** Gemini Live, plus an opt-in "Hey Orbit" wake word (Edge; Chrome's speech service may not connect).
- **Accounts:** sign up / sign in with Google or email + password (Firebase Auth, verified email). Each account has
  its own conversations, bookings, statement and switches (Firestore), can **Connect Google** to read its real
  calendar and inbox (read-only), and can **Delete my data**.

More: [docs/PLAN.md](docs/PLAN.md) · [docs/TEAM_BRIEF.md](docs/TEAM_BRIEF.md) · [contracts/](contracts/) ·
Google + Firebase setup: [docs/GOOGLE_SETUP.md](docs/GOOGLE_SETUP.md)

## Setup (Windows)

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
copy frontend\.env.example frontend\.env.local
cd frontend && npm ci && cd ..
```

Fill in `.env` (every setting is explained in [.env.example](.env.example)). Only `GEMINI_API_KEY` and a way to sign in
(`ORBIT_DEMO_EMAIL` + `ORBIT_DEMO_PASSWORD`, or Firebase) are needed to start; everything else falls back to sample
data or switches itself off:

| Feature | Settings |
|---|---|
| The AI (planning, voice) | `GEMINI_API_KEY` |
| Live flight, hotel and price search | `SERPAPI_API_KEY` |
| Duffel test-mode flight bookings | `DUFFEL_ACCESS_TOKEN` (a `duffel_test_…` token; live tokens are refused) |
| Google / email sign-in | `FIREBASE_PROJECT_ID`, `ORBIT_ALLOWED_EMAILS`, and `frontend/.env.local` |
| Data in Firestore (instead of `data/session/orbit.db`) | `FIREBASE_SERVICE_ACCOUNT` |
| Connect Google (read your calendar + inbox) | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ORBIT_TOKEN_KEY` |
| Booking confirmations (email + calendar) | `ORBIT_NOTIFY_URL`, `ORBIT_NOTIFY_SECRET` |
| WhatsApp / SMS booking alerts (Twilio) | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`, `ORBIT_ALERTS` |
| Telegram booking alerts (anyone who scans the QR) | `TELEGRAM_BOT_TOKEN` |

**Never commit** `.env`, `frontend/.env.local`, the Firebase service-account key, `credentials.json`, `token.json`,
`data/raw/`, `data/session/` or `*_cache.json` (all gitignored).

## Run (three terminals, from the repo root)

```bash
.venv\Scripts\python run_servers.py
.venv\Scripts\python backend\main.py
npm --prefix frontend run dev
```

- **`run_servers.py`** starts the MCP servers: calendar :8101 · gmail :8102 · finance :8103 · travel :8104 ·
  price :8105 · booking :8106, each at `http://127.0.0.1:<port>/mcp`.
- **`backend\main.py`** is the API on :8000 (the endpoint list is at the top of the file). You sign in again after
  every backend start.
- **The UI** runs at http://localhost:4173 (127.0.0.1 forwards there, for Google sign-in) and proxies `/api` to :8000.

Try it: sign in → switch **Finance** on → **Add balance** → pick a sample statement → ask
*"Book a Goa trip next weekend"* → open **Bookings** → **Approve**.

`ORBIT_OFFLINE=1` forces cached/sample data everywhere (no Google, no SerpAPI): the save-the-demo switch.

## Tests

```bash
.venv\Scripts\python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

The tests never touch your real data, Google, Duffel or Firestore. The Firestore check runs only on demand:
`FIREBASE_SERVICE_ACCOUNT=firebase-service-account.json .venv\Scripts\python -m pytest tests/test_store_firestore.py`.

## Team

| Role | Who | Owns |
|---|---|---|
| A | Sai Siddarth | Frontend and design |
| B | Sai Gowrav | MCP servers, registry |
| C | Samarth Anil | AI Integrations: Gemini loop, engine, Guardian, injection |
| D | Pramegha M | Data, API integration, tests, pitch |
