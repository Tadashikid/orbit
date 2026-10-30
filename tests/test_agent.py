"""Guardian + the Gemini loop with a fake model (no network): the model can ask, only Guardian decides."""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from google.genai import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import agent  # noqa: E402
import guardian  # noqa: E402

CATALOGUE = [
    {"name": "finance__get_balance", "description": "", "input_schema": {"type": "object", "properties": {}}, "read_only": True},
    {"name": "finance__load_statement", "description": "", "input_schema": {"type": "object", "properties": {"statement": {"type": "string"}}},
     "read_only": False},
]


def reply(*calls, text=None):
    parts = [types.Part(function_call=types.FunctionCall(id=f"c{i}", name=n, args=a)) for i, (n, a) in enumerate(calls)]
    parts += [types.Part.from_text(text=text)] if text else []
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=parts))])


def test_guardian_rules():
    assert guardian.check("finance__get_balance", CATALOGUE) == ("allowed", "")
    assert guardian.check("finance__load_statement", CATALOGUE)[0] == "needs_approval"
    assert guardian.check("finance__set_balance", CATALOGUE)[0] == "blocked"  # what the injected email asks for: no such tool
    assert guardian.check("email__send_everything", CATALOGUE)[0] == "blocked"


def _tool(name, read_only=True):
    return {"name": name, "description": "", "input_schema": {}, "read_only": read_only}


def test_server_cannot_vouch_for_itself():
    # A plugged-in server says its new tool is read-only: not on Orbit's list, so it doesn't run.
    assert guardian.check("finance__export_all", [_tool("finance__export_all")]) == ("blocked", "not on Orbit's reviewed tool list")
    # A listed read tool that the server now marks as a write: the stricter answer wins.
    assert guardian.check("finance__get_balance", [_tool("finance__get_balance", read_only=False)])[0] == "needs_approval"


def test_private_data_cannot_leave_in_an_outbound_search():
    guard = guardian.Guard([_tool("finance__get_balance"), _tool("price__check_price")], "Can I buy a phone under 30,000?")
    guard.saw({"server": "finance", "tool": "get_balance", "ok": True,
               "result": {"balance": 54263, "as_of": "2026-10-08", "contact": "manu@example.com", "limit": 30000}})
    assert guard.check("price__check_price", {"item": "laptop for balance 54,263"}) == ("blocked", "would send your private data to a third party")
    assert guard.check("price__check_price", {"item": "manu@example.com"})[0] == "blocked"
    assert guard.check("price__check_price", {"item": "phone under 30000"})[0] == "allowed"  # the user typed it
    assert guard.check("price__check_price", {"item": "iPhone 16 2026-10-10"})[0] == "allowed"  # no false hit on dates


def test_call_budget_stops_a_looping_model():
    guard = guardian.Guard([_tool("price__check_price"), _tool("finance__get_balance")])
    asked = [guard.check("price__check_price", {"item": f"phone {i}"})[0] for i in range(guardian.MAX_OUTBOUND + 1)]
    assert asked[-1] == "blocked" and asked.count("allowed") == guardian.MAX_OUTBOUND
    assert guard.check("finance__get_balance")[0] == "allowed"  # private reads still have budget left


def test_audit_log_records_decisions_not_results(tmp_path, monkeypatch):
    monkeypatch.setattr(guardian, "AUDIT_LOG", tmp_path / "audit.jsonl")
    guardian.audit("Can I afford Goa?", [{"server": "finance", "tool": "load_statement", "args": {}, "ok": False, "ms": 0,
                                          "by": "gemini", "guardian": "needs_approval", "error": guardian.WRITE, "result": {"balance": 1}}])
    row = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8"))
    assert row["question"] == "Can I afford Goa?" and row["calls"][0]["guardian"] == "needs_approval"
    assert "result" not in row["calls"][0]


def test_model_asking_for_a_write_is_stopped_in_code():
    # A fooled model (e.g. by the injected email) tries to swap in a forged statement alongside a normal read.
    turns = iter([reply(("finance__get_balance", {}), ("finance__load_statement", {"statement": "date,category,debit,credit,balance (a forged statement: 1 crore)"})), reply(text="DONE")])
    ran = []

    async def generate(contents, config, chain):
        return "fake-model", next(turns)

    async def call_tool(name, args):
        ran.append(name)
        return {"server": "finance", "tool": name.split("__")[1], "args": args, "ok": True, "result": {"balance": 21842}, "ms": 1}

    model, executed, trace, _ = asyncio.run(agent.gather(
        "Can I afford Goa?", "facts", CATALOGUE, call_tool, lambda n, a: guardian.check(n, CATALOGUE, a), generate, ["fake-model"]))
    assert model == "fake-model"
    assert ran == ["finance__get_balance"]  # load_statement never reached the server
    blocked = [t for t in trace if t["guardian"] != "allowed"]
    assert blocked[0].pop("ts")  # when Guardian stopped it (a real timestamp, for the trace)
    assert blocked == [{"server": "finance", "tool": "load_statement", "args": {"statement": "date,category,debit,credit,balance (a forged statement: 1 crore)"}, "ok": False, "ms": 0,
                        "by": "gemini", "guardian": "needs_approval", "error": "write tool: only you can approve this, not the AI"}]


def test_no_model_answering_raises_so_rules_planner_takes_over():
    async def generate(contents, config, chain):
        raise RuntimeError("gemini-3.8-flash: ServerError 503")

    with pytest.raises(RuntimeError):
        asyncio.run(agent.gather("q", "facts", CATALOGUE, None, None, generate, ["gemini-3.8-flash"]))
