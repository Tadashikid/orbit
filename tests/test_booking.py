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
    monkeypatch.delenv("DUFFEL_ACCESS_TOKEN", raising=False)  # the sandbox, unless a test turns Duffel on


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


def _offer(oid, airline, amount, holdable=True):
    return {"id": oid, "owner": {"name": airline}, "total_amount": amount, "passengers": [{"id": "pas_1"}],
            "payment_requirements": {"requires_instant_payment": not holdable}}


@pytest.fixture
def duffel(monkeypatch):
    """A fake Duffel (no network) that records every call."""
    monkeypatch.setenv("DUFFEL_ACCESS_TOKEN", "duffel_test_fake")
    calls, order = [], {"id": "ord_1", "total_amount": "91.20", "total_currency": "GBP", "booking_reference": "RZPNX8",
                        "payment_status": {"payment_required_by": "2099-01-01T10:00:00Z"}}

    def fake(method, path, body=None):
        calls.append((method, path, body))
        if path.startswith("/air/offer_requests"):
            return {"offers": [_offer("off_cheap_instant", "Duffel Airways", "40.00", holdable=False),
                               _offer("off_other", "British Airways", "80.00"),
                               _offer("off_same", "Duffel Airways", "95.00"), _offer("off_same2", "Duffel Airways", "91.20")]}
        if method == "POST" and path == "/air/orders":
            return order
        if path == "/air/orders/ord_1":
            return order
        if path == "/air/payments":
            return {"id": "pay_1"}
        raise AssertionError(path)

    monkeypatch.setattr(b, "_duffel", fake)
    return calls, order


def test_duffel_hold_then_pay_from_test_balance(duffel):
    calls, _ = duffel
    h = b.hold_flight("blr", "goi", "2026-11-07", "Duffel Airways", "21:00", 6411)
    # the cheapest fare that can be held, from the airline Orbit priced; the instant-payment one is skipped
    assert calls[1] == ("POST", "/air/orders", {"data": {"type": "hold", "selected_offers": ["off_same2"],
                                                         "passengers": [{"id": "pas_1", **b.TEST_TRAVELLER}]}})
    assert (h["amount"], h["currency"], h["sandbox"], h["expires_at"]) == (91.2, "GBP", False, "2099-01-01T10:00:00Z")
    assert h["summary"] == "Duffel Airways BLR→GOI Sat 07 Nov · Duffel test"
    done = b.confirm_hold(h["hold_id"])
    assert calls[-2] == ("POST", "/air/payments", {"data": {"order_id": "ord_1", "payment": {
        "type": "balance", "amount": "91.20", "currency": "GBP"}}})  # the exact price you approved
    assert (done["status"], done["reference"]) == ("confirmed", "RZPNX8") and "no real money" in done["payment"]


def test_duffel_price_change_stops_the_payment(duffel):
    calls, order = duffel
    h = b.hold_flight("BLR", "GOI", "2026-11-07", "IndiGo", "21:00", 6411)  # no IndiGo: cheapest holdable instead
    assert calls[1][2]["data"]["selected_offers"] == ["off_other"]
    order["total_amount"] = "99.90"
    with pytest.raises(ValueError, match="price changed to GBP 99.90"):
        b.confirm_hold(h["hold_id"])
    assert not any(path == "/air/payments" for _, path, _ in calls)
    assert b._load()[h["hold_id"]]["status"] == "held"  # nothing paid, still yours to look at again


def test_live_duffel_tokens_are_refused(monkeypatch):
    monkeypatch.setenv("DUFFEL_ACCESS_TOKEN", "duffel_live_real_money")
    assert b._duffel_token() is None
    h = b.hold_flight("BLR", "GOI", "2026-11-07", "IndiGo", "21:00", 6411)
    assert h["sandbox"] is True and h["currency"] == "INR"  # the sandbox, never a real ticket
