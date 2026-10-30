import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from registry import Registry  # noqa: E402

pytestmark = pytest.mark.usefixtures("mcp_servers")  # tests/conftest.py


def test_hot_plug_adds_finance_tools():
    reg = Registry()
    before = asyncio.run(reg.discover())
    assert before["offline"] == {}
    assert {t["name"] for t in before["tools"]} == {
        "calendar__list_events", "calendar__find_free_slots", "gmail__list_tasks", "gmail__get_deadlines"}

    reg.plug("finance")
    after = asyncio.run(reg.discover())
    added = {t["name"] for t in after["tools"]} - {t["name"] for t in before["tools"]}
    assert added == {f"finance__{n}" for n in ("load_statement", "get_balance", "get_sips", "get_spending_summary", "get_cost_table")}
    assert [t["name"] for t in after["tools"] if not t["read_only"]] == ["finance__load_statement"]


def test_call_routing_and_failures():
    reg = Registry()
    assert asyncio.run(reg.call("finance__get_balance"))["ok"] is False  # not plugged in yet

    reg.plug("finance")
    r = asyncio.run(reg.call("finance__get_balance"))
    assert r["ok"] and r["result"]["currency"] == "INR" and r["server"] == "finance"

    bad = asyncio.run(reg.call("finance__get_spending_summary", {"days": 0}))
    assert bad["ok"] is False and "days must be" in bad["error"]
    assert asyncio.run(reg.call("finance__no_such_tool"))["ok"] is False


def test_offline_server_does_not_break_discovery():
    reg = Registry()
    reg.plug("ghost", "http://127.0.0.1:8199/mcp")  # nothing listens there
    cat = asyncio.run(reg.discover())
    assert "ghost" in cat["offline"] and len(cat["tools"]) == 4
    assert asyncio.run(reg.call("ghost__anything"))["ok"] is False
