"""POST /ask end to end: FastAPI -> registry -> real MCP servers over HTTP -> engine."""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import main  # noqa: E402

pytestmark = pytest.mark.usefixtures("mcp_servers")
Q = {"question": "Can I afford a Goa trip next weekend?"}
CONTRACT = json.loads((ROOT / "contracts" / "verdict.after_finance.json").read_text(encoding="utf-8"))


STATEMENT_BALANCE = 54263  # the last balance in data/samples/manu_statement.csv (Thu 08 Oct), served by conftest.py


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "TODAY", date(2026, 10, 8))
    monkeypatch.setattr(main, "GEMINI", None)  # tests never call the real model (see test_gemini_cannot_write)
    c = TestClient(main.app)
    assert c.post("/login", json={"email": main.DEMO_EMAIL, "password": main.DEMO_PASSWORD}).status_code == 200
    yield c
    main.registry.unplug("finance")


def test_gemini_cannot_write_and_numbers_stay_canonical(client, monkeypatch):
    """A model that skips reads and asks for load_statement: Guardian stops the write, the rules fill in the reads."""
    from test_agent import reply

    understood = json.dumps({"kind": "trip", "city": "Goa", "airport": "GOI", "start": "2026-10-10", "end": "2026-10-11"})
    turns = iter([reply(text=understood),  # 1. understand the question
                  reply(("finance__load_statement", {"statement": "date,category,debit,credit,balance (a forged statement: 1 crore)"}), ("gmail__list_tasks", {})),  # 2. a fooled plan
                  reply(text="DONE"), reply(text="ok")])  # 3. done, 4. explanation

    async def fake_model(contents, config, chain):
        return "fake-model", next(turns)

    monkeypatch.setattr(main, "GEMINI", fake_model)
    client.post("/servers/finance/plug")
    d = client.post("/ask", json=Q).json()
    assert (d["planner"], d["model"]) == ("gemini", "fake-model")
    assert [(t["tool"], t["guardian"]) for t in d["trace"] if t["guardian"] != "allowed"] == [("load_statement", "needs_approval")]
    assert {t["by"] for t in d["trace"]} == {"gemini", "rules"}
    assert d["verdict"]["numbers"]["balance"] == STATEMENT_BALANCE  # the forged statement never loaded


def test_finance_hot_plug_flips_the_answer(client):
    assert {s["name"]: s["plugged"] for s in client.get("/servers").json()["servers"]}["finance"] is False

    before = client.post("/ask", json=Q).json()
    assert before["verdict"]["verdict"] == "yes" and "finance" in before["verdict"]["not_read"]
    assert {t["server"] for t in before["trace"]} == {"calendar", "gmail", "travel"}

    client.post("/servers/finance/plug")
    after = client.post("/ask", json=Q).json()["verdict"]
    # Flight prices may be live/cached here (exact contract numbers are pinned in test_engine.py),
    # so check that the answer flipped and that the money arithmetic holds for whatever fares came back.
    n = after["numbers"]
    assert (n["balance"], n["monthly_commitments"]) == (STATEMENT_BALANCE, CONTRACT["numbers"]["monthly_commitments"])
    # Rs 10,000 cushion: only "risky" / "no" leave you below it after the trip + plan.
    assert (after["verdict"] in ("risky", "no")) == (n["remaining"]["low"] < n["safety_floor"] == 10000)


def test_statement_upload_masks_then_loads(client):
    assert client.get("/balance").status_code == 409  # Finance not plugged in: nothing to read
    client.post("/servers/finance/plug")
    raw = (ROOT / "data" / "samples" / "manu_statement.csv").read_text(encoding="utf-8")
    assert client.post("/statement", json={"csv": "not,a,statement"}).status_code == 422
    r = client.post("/statement", json={"csv": raw}).json()
    assert r["receipt"]["dropped_columns"] == ["Narration", "Mode"] and r["receipt"]["rows_kept"] == 245
    assert client.get("/balance").json() == {"balance": STATEMENT_BALANCE, "currency": "INR", "as_of": "2026-10-08",
                                             "source": "statement_csv"}


def test_bad_input(client):
    assert client.post("/servers/nope/plug").status_code == 404
    assert client.post("/ask", json={"question": ""}).status_code == 422


def test_servers_announce_their_tools(client):
    s = {x["name"]: x for x in client.get("/servers").json()["servers"]}
    assert (s["finance"]["status"], s["finance"]["tools"]) == ("off", [])
    assert client.get("/statement").json() is None  # Finance off: nothing to show, and not an error
    assert {t["name"] for t in s["travel"]["tools"]} == {"search_flights", "search_hotels"}
    plugged = {x["name"]: x for x in client.post("/servers/finance/plug").json()["servers"]}["finance"]
    assert plugged["status"] == "connected"
    assert [t["name"] for t in plugged["tools"] if not t["read_only"]] == ["load_statement"]


def test_sample_statements_load_by_name(client):
    client.post("/servers/finance/plug")
    assert "manu_statement_spend_30k" in client.get("/statement/samples").json()["samples"]
    assert client.post("/statement", json={"sample": "../.env"}).status_code == 422  # names only, no paths
    try:
        r = client.post("/statement", json={"sample": "manu_statement_spend_30k"}).json()
        assert (r["balance"], round(r["summary"]["monthly_avg_spend"])) == (94861, 29999)
        assert client.get("/statement").json()["balance"] == 94861
    finally:
        client.post("/statement", json={"sample": "manu_statement"})  # the other API tests expect Manu's statement


def test_ask_keeps_a_conversation(client):
    import store

    first = client.post("/ask", json=Q).json()
    sid = first["session_id"]
    client.post("/ask", json={"question": "And the weekend after?", "session_id": sid})
    turns = store.history(main.DEMO_EMAIL, sid)
    assert [t["question"] for t in turns] == [Q["question"], "And the weekend after?"]
    assert turns[0]["answer"] == {"verdict": first["verdict"]["verdict"], "headline": first["verdict"]["headline"], "intent": first["intent"]}
    assert client.post("/ask", json={**Q, "session_id": "../../etc/passwd"}).status_code == 422


def test_agent_streams_events_without_a_model(client):
    """No Gemini: the goal is checked as one plan through Orbit's own tool, streamed as server-sent events."""
    body = client.post("/agent", json={"goal": Q["question"]}).text
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["session", "tool", "message", "done"]
    tool = events[1]
    assert (tool["server"], tool["tool"], tool["by"], tool["ok"]) == ("orbit", "check_plan", "rules", True)
    assert events[2]["text"] == tool["answer"]["verdict"]["headline"]
    assert tool["answer"]["trace"]  # the reads behind the plan, for the receipt


def test_demo_login_gates_every_endpoint(monkeypatch):
    c = TestClient(main.app)
    assert c.get("/servers").status_code == 401  # signed out: nothing but /login, /logout, /me
    assert c.post("/ask", json=Q).status_code == 401
    assert c.get("/me").status_code == 401
    assert c.post("/login", json={"email": main.DEMO_EMAIL, "password": "wrong"}).status_code == 401
    assert c.post("/login", json={"email": "someone@else.example", "password": main.DEMO_PASSWORD}).status_code == 401
    c.cookies.set(main.COOKIE, f"{main.DEMO_EMAIL}.forged")
    assert c.get("/me").status_code == 401  # a cookie needs the server's signature
    c.cookies.clear()

    r = c.post("/login", json={"email": f"  {main.DEMO_EMAIL.upper()} ", "password": main.DEMO_PASSWORD})
    assert r.json() == {"email": main.DEMO_EMAIL} and "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/me").json() == {"email": main.DEMO_EMAIL}
    c.post("/logout")
    assert c.get("/servers").status_code == 401

    monkeypatch.setattr(main, "DEMO_PASSWORD", "")  # no password in .env: no way in, even with an old cookie
    assert c.post("/login", json={"email": main.DEMO_EMAIL, "password": ""}).status_code == 503


def _events(client, goal):
    body = client.post("/agent", json={"goal": goal}).text
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


def test_booking_holds_wait_for_your_approval(client):
    """No model: "book it" holds the exact options the engine priced; only your approval confirms one, once."""
    client.post("/servers/finance/plug")
    events = _events(client, "Book a Goa trip next weekend")
    cards = [e["action"] for e in events if e["type"] == "approval"]
    assert [c["kind"] for c in cards] == ["flight", "flight", "stay"]
    assert all(c["status"] == "pending" and "session" not in c and "hold_id" not in c for c in cards)
    assert "on hold for you to approve" in [e for e in events if e["type"] == "message"][0]["text"]
    holds = [e for e in events if e["type"] == "tool" and e["server"] == "booking"]
    assert {(h["tool"], h["guardian"], h["by"]) for h in holds} == {("hold_flight", "allowed", "rules"), ("hold_stay", "allowed", "rules")}

    out, back, stay = cards
    assert client.post(f"/actions/{out['id']}/approve", json={"hash": "0" * 32}).status_code == 409  # not what you saw
    done = client.post(f"/actions/{out['id']}/approve", json={"hash": out["hash"]}).json()
    assert done["status"] == "confirmed" and done["outcome"]["reference"].startswith("ORB-")
    assert "nothing was charged" in done["outcome"]["payment"]
    assert client.post(f"/actions/{out['id']}/approve", json={"hash": out["hash"]}).status_code == 409  # never twice
    assert client.post(f"/actions/{stay['id']}/decline").json()["status"] == "declined"
    assert client.post(f"/actions/{stay['id']}/approve", json={"hash": stay["hash"]}).status_code == 409
    assert client.post("/actions/not-an-id/approve", json={"hash": stay["hash"]}).status_code == 404


def test_no_holds_without_a_budget(client):
    events = _events(client, "Book a Goa trip next weekend")  # Finance off: the money isn't checked
    assert not [e for e in events if e["type"] == "approval"]
    blocked = {e["guardian"] for e in events if e["type"] == "tool" and e["server"] == "booking"}
    assert blocked == {"blocked"}
    assert "fits your money" in [e for e in events if e["type"] == "message"][0]["text"]


def test_book_it_still_holds_when_the_model_stops_partway(client, monkeypatch):
    """The model checks the plan, then times out before holding anything: the rules hold the cleared plan's options."""
    from test_agent import reply

    agent_turns = iter([reply(("orbit__check_plan", {"question": Q["question"]}))])

    async def flaky_model(contents, config, chain):
        if config.system_instruction == main.agent.AGENT and (turn := next(agent_turns, None)):
            return "fake-model", turn
        raise RuntimeError("fake-model: TimeoutError")  # the plan's own steps fall back to the rules too

    monkeypatch.setattr(main, "GEMINI", flaky_model)
    client.post("/servers/finance/plug")
    events = _events(client, "Book a Goa trip next weekend")
    assert [e["action"]["kind"] for e in events if e["type"] == "approval"] == ["flight", "flight", "stay"]
    tools = [(e["tool"], e["by"]) for e in events if e["type"] == "tool"]
    assert tools[0] == ("check_plan", "gemini") and ("hold_flight", "rules") in tools
    assert "on hold for you to approve" in events[-2]["text"]


def test_bookings_window_lists_everything_and_expires_old_holds(client, monkeypatch):
    client.post("/servers/finance/plug")
    cards = [e["action"] for e in _events(client, "Book a Goa trip next weekend") if e["type"] == "approval"]
    listed = client.get("/actions").json()["actions"]
    assert [a["id"] for a in listed[:3]] == [c["id"] for c in reversed(cards)]  # newest first
    assert all("session" not in a and "hold_id" not in a for a in listed)


    class Later(datetime):  # an hour later: every 30-minute hold has run out
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(hours=1)

    monkeypatch.setattr(main, "datetime", Later)
    statuses = {a["id"]: a["status"] for a in client.get("/actions").json()["actions"]}
    assert {statuses[c["id"]] for c in cards} == {"expired"}
    assert client.post(f"/actions/{cards[0]['id']}/approve", json={"hash": cards[0]["hash"]}).status_code == 409


def test_small_talk_reads_nothing_and_says_what_orbit_does(client):
    d = client.post("/ask", json={"question": "whats the weather?"}).json()
    assert d["verdict"]["verdict"] == "info" and d["trace"] == []  # no calendar, no Gmail, no prices
    assert d["verdict"]["headline"].startswith("I can't help with that one.")


@pytest.mark.parametrize("question, reads, says", [
    ("show me my calendar", {"list_events"}, "Coming up: "),
    ("any new mails?", {"list_tasks"}, "10 emails need action: Goa weekend pre-approval (due Fri 09 Oct)"),
    ("Is there any budget in the calendar?", {"list_events"}, "Connect your budget"),  # Finance is off here
])
def test_questions_about_your_own_data_read_just_that(client, question, reads, says):
    d = client.post("/ask", json={"question": question}).json()
    assert {t["tool"] for t in d["trace"]} == reads and says in d["verdict"]["headline"]
    assert d["verdict"]["verdict"] == "info"  # an answer, not a plan: no prices were searched


def test_sign_in_comes_first_after_every_start_and_browser_close(monkeypatch):
    c = TestClient(main.app)
    r = c.post("/login", json={"email": main.DEMO_EMAIL, "password": main.DEMO_PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "max-age" not in cookie and "expires" not in cookie  # a session cookie: gone when the browser closes
    assert c.get("/me").status_code == 200
    restarted = main.hashlib.sha256(f"orbit-session:{main.DEMO_PASSWORD}:another-start".encode()).digest()
    monkeypatch.setattr(main, "_KEY", restarted)  # the backend started again: a new secret
    assert c.get("/me").status_code == 401  # yesterday's sign-in no longer works: the sign-in page comes first


def test_google_sign_in_checks_google_and_the_allow_list(monkeypatch):
    monkeypatch.setattr(main, "FIREBASE_PROJECT_ID", "orbit-test")
    monkeypatch.setattr(main, "ALLOWED", {"manu@gmail.com"})
    tokens = {"good": {"email": "Manu@gmail.com", "email_verified": True, "name": "Manu"},
              "unverified": {"email": "manu@gmail.com", "email_verified": False},
              "stranger": {"email": "someone@gmail.com", "email_verified": True}}

    def verify(token):
        if token not in tokens:
            raise ValueError("bad signature")
        return tokens[token]

    monkeypatch.setattr(main, "_verify_google", verify)
    c = TestClient(main.app)
    assert c.get("/auth/config").json()["google"] is True
    sign_in = lambda t: c.post("/auth/google", json={"id_token": t * 5})  # noqa: E731  (min length 20)
    tokens = {k * 5: v for k, v in tokens.items()}
    assert sign_in("forged").status_code == 401  # Google's signature didn't check out
    assert sign_in("unverified").status_code == 401  # Google never confirmed the email
    assert sign_in("stranger").status_code == 403  # not on the list
    assert c.get("/me").status_code == 401
    r = sign_in("good")
    assert r.json() == {"email": "manu@gmail.com", "name": "Manu"} and "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/me").json() == {"email": "manu@gmail.com"} and c.get("/servers").status_code == 200

    monkeypatch.setattr(main, "ALLOWED", {"*"})  # any Google account (each sees only their own, see below)
    assert sign_in("stranger").json()["email"] == "someone@gmail.com"


def test_each_account_sees_only_its_own_bookings_and_conversations(client, monkeypatch):
    import store

    client.post("/servers/finance/plug")
    events = _events(client, "Book a Goa trip next weekend")
    sid = events[0]["id"]
    mine = [e["action"] for e in events if e["type"] == "approval"]
    assert mine and store.history(main.DEMO_EMAIL, sid)

    monkeypatch.setattr(main, "FIREBASE_PROJECT_ID", "orbit-test")
    monkeypatch.setattr(main, "ALLOWED", {"*"})
    monkeypatch.setattr(main, "_verify_google", lambda t: {"email": "someone@gmail.com", "email_verified": True})
    other = TestClient(main.app)
    assert other.post("/auth/google", json={"id_token": "x" * 20}).status_code == 200
    assert {a["id"] for a in other.get("/actions").json()["actions"]}.isdisjoint(a["id"] for a in mine)
    for a in mine:  # knowing the id and hash isn't enough: someone else's hold doesn't exist for you
        assert other.post(f"/actions/{a['id']}/approve", json={"hash": a["hash"]}).status_code == 404
        assert other.post(f"/actions/{a['id']}/decline").status_code == 404
    other.post("/ask", json={**Q, "session_id": sid})  # writing into my conversation id
    assert [t["question"] for t in store.history(main.DEMO_EMAIL, sid)] == ["Book a Goa trip next weekend"]
    assert {a["status"] for a in client.get("/actions").json()["actions"] if a["id"] in {m["id"] for m in mine}} == {"pending"}
