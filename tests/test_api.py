"""POST /ask end to end: FastAPI -> registry -> real MCP servers over HTTP -> engine."""
import json
import sys
from datetime import date
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
    yield TestClient(main.app)
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
