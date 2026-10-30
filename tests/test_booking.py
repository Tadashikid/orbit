"""The sandbox booking server: holds are free and expire; only confirm_hold is a commit, and it never books twice."""
import asyncio
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_servers"))
import booking_server as b  # noqa: E402


@pytest.fixture(autouse=True)
def holds(monkeypatch, tmp_path):
    monkeypatch.setattr(b, "HOLDS", tmp_path / "holds.json")


def test_only_confirm_is_destructive():
    tools = {t.name: t.annotations for t in asyncio.run(b.mcp.list_tools())}
    assert set(tools) == {"hold_flight", "hold_stay", "hold_order", "release_hold", "confirm_hold"}
    assert {n for n, a in tools.items() if a.destructiveHint} == {"confirm_hold"}
    assert not any(a.readOnlyHint for a in tools.values())


def test_holds_then_confirm_once():
    f = b.hold_flight("blr", "goi", "2026-11-07", "IndiGo", "21:00", 6411)
    assert (f["kind"], f["summary"], f["amount"], f["status"]) == ("flight", "IndiGo BLR→GOI Sat 07 Nov 21:00", 6411, "held")
    s = b.hold_stay("Goa", "2026-11-07", "2026-11-09", "Vibes Inn", 791)
    assert (s["amount"], s["summary"]) == (1582, "Vibes Inn, Goa · 2 nights from Sat 07 Nov")
    done = b.confirm_hold(f["hold_id"])
    assert done["status"] == "confirmed" and done["reference"].startswith("ORB-") and "nothing was charged" in done["payment"]
    assert b.confirm_hold(f["hold_id"])["reference"] == done["reference"]  # a retry doesn't book twice
    assert b.release_hold(s["hold_id"])["status"] == "released"
    with pytest.raises(ValueError, match="is released"):
        b.confirm_hold(s["hold_id"])


def test_bad_holds_are_refused(monkeypatch):
    with pytest.raises(ValueError, match="whole number"):
        b.hold_order("iPhone 16", "Amazon.in", 0)
    with pytest.raises(ValueError, match="whole number"):
        b.hold_order("iPhone 16", "Amazon.in", 50_00_00_000)  # Rs 50 crore
    with pytest.raises(ValueError, match="1 to 30 nights"):
        b.hold_stay("Goa", "2026-11-09", "2026-11-07", "Vibes Inn", 791)
    o = b.hold_order("iPhone 16", "Amazon.in", 69900)
    real_now = b._now
    monkeypatch.setattr(b, "_now", lambda: real_now() + timedelta(minutes=b.HOLD_MINUTES + 1))
    with pytest.raises(ValueError, match="expired"):
        b.confirm_hold(o["hold_id"])
