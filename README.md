# Orbit

**Everything revolves around your life. Orbit decides with you, and shows its evidence.**

Orbit answers questions like *"Can I afford a Goa trip next weekend?"* using your real constraints: calendar, deadlines, spending, and commitments. Each source plugs in through MCP, and you control which sources it may read. Permissions are enforced in code, the money math is deterministic Python, and every answer comes with a data receipt showing what was read, from where, and how fresh it was.

- **Plan / save-the-demo:** [docs/PLAN.md](docs/PLAN.md)
- **Spec:** [docs/TEAM_BRIEF.md](docs/TEAM_BRIEF.md)
- **Engine ↔ UI contract:** [contracts/](contracts/)
- **Demo persona data (Manu, synthetic):** [data/](data/)

## Setup (Windows)

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
cd frontend && npm ci && cd ..
```

Put your keys in `.env`. **Never commit `.env`**, `credentials.json`, `token.json`, `data/raw/`, `data/session/` or `*_cache.json`.

## Run (three terminals, from the repo root)

```bash
.venv\Scripts\python run_servers.py
.venv\Scripts\python backend\main.py
cd frontend && npm run dev
```

- **`run_servers.py`** starts the MCP servers: calendar :8101 · gmail :8102 · finance :8103 · travel :8104 · price :8105, each at `http://127.0.0.1:<port>/mcp`.
- **`backend\main.py`** is the API on :8000: `POST /ask`, `GET /servers`, `POST /servers/{name}/plug|unplug`, `GET|POST /statement`.
- **The UI** (React + TypeScript + Vite) runs at http://localhost:4173 (127.0.0.1 forwards there, for Google sign-in) and proxies `/api` to :8000.

In the UI: ask a question → **Add your budget** (plugs Finance) → **Add a statement** → upload a CSV from `data/samples/` → **Check my plan again**.

Calendar and Gmail use seeded data until you sign in (see [docs/GOOGLE_SETUP.md](docs/GOOGLE_SETUP.md)). Set `ORBIT_OFFLINE=1` to force cache/seeded data everywhere.

## Tests

```bash
.venv\Scripts\python -m pytest -q
cd frontend && npm test && npm run build
```

## Team

| Role | Who | Owns |
|---|---|---|
| A | Sai Siddarth | Frontend and design |
| B | Sai Gowrav | MCP servers, registry |
| C | Samarth Anil | AI Integrations: Gemini loop, engine, Guardian, injection |
| D | Pramegha M | Data, API integration, tests, pitch |
