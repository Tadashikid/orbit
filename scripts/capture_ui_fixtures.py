"""Record real Orbit API responses for the frontend tests: frontend/tests/fixtures/backend.json.

The UI tests replay these through a fake fetch, so they exercise the real response schema without a running backend.
Runs the real backend and MCP servers on their own ports (8601-8605), offline (seeded data, no Google, no SerpAPI),
on the demo date 2026-10-08 with Manu's sample statement. Re-run it whenever the API's responses change:

    .venv\\Scripts\\python scripts\\capture_ui_fixtures.py
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "tests" / "fixtures" / "backend.json"
SCRATCH = Path(tempfile.mkdtemp())  # its own statement and an empty search cache: only seeded data
os.environ.update(ORBIT_PORT_OFFSET="500", ORBIT_OFFLINE="1", ORBIT_TODAY="2026-10-08", ORBIT_DEMO_PASSWORD=secrets.token_urlsafe(16),
                  ORBIT_DB=str(Path(tempfile.mkdtemp()) / "orbit.db"), ORBIT_AUDIT_LOG=str(Path(tempfile.mkdtemp()) / "audit.jsonl"),
                  ORBIT_STATEMENT=str(SCRATCH / "statement.csv"), ORBIT_CACHE_DIR=str(SCRATCH),
                  ORBIT_HOLDS=str(SCRATCH / "holds.json"))
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

HERO = "Can I afford a Goa trip next weekend?"
QUESTIONS = ["Can I buy a table?", "Can I go to a fancy dinner this Saturday with 3 friends?", "Should I learn guitar?"]


def wait_for(ports):
    deadline = time.time() + 20
    for port in ports:
        while socket.socket().connect_ex(("127.0.0.1", port)):
            if time.time() > deadline:
                sys.exit(f"MCP server on {port} did not start")
            time.sleep(0.2)


def main_():
    procs = [subprocess.Popen([sys.executable, str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for p in sorted((ROOT / "mcp_servers").glob("*_server.py"))]
    try:
        wait_for([8601, 8602, 8603, 8604, 8605, 8606])
        main.GEMINI = None  # the rules planner: deterministic
        c = TestClient(main.app)
        c.post("/login", json={"email": main.DEMO_EMAIL, "password": main.DEMO_PASSWORD})
        ask = lambda q: c.post("/ask", json={"question": q}).json()  # noqa: E731
        r = {"GET /servers": c.get("/servers").json(), "ask_without_finance": {HERO: ask(HERO)}}
        r["POST /servers/finance/plug"] = c.post("/servers/finance/plug").json()
        r["GET /statement (none yet)"] = c.get("/statement").json()
        r["GET /statement/samples"] = c.get("/statement/samples").json()
        r["POST /statement"] = c.post("/statement", json={"sample": "manu_statement"}).json()
        r["GET /statement"] = c.get("/statement").json()
        r["ask_with_finance"] = {q: ask(q) for q in [HERO, *QUESTIONS]}
    finally:
        for p in procs:
            p.terminate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    note = "Captured from backend/main.py by scripts/capture_ui_fixtures.py (offline, seeded data, 2026-10-08)."
    OUT.write_text(json.dumps({"_note": note, **r}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main_()
