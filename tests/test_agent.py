"""Guardian + the Gemini loop with a fake model (no network): the model can ask, only Guardian decides."""
import asyncio
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
        "Can I afford Goa?", "facts", CATALOGUE, call_tool, lambda n: guardian.check(n, CATALOGUE), generate, ["fake-model"]))
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
