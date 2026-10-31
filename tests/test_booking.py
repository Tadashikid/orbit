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
    assert h["summary"] == "Duffel Airways BLR→GOI Sat 07 Nov · Duffel test hold"
    done = b.confirm_hold(h["hold_id"])
    assert calls[-2] == ("POST", "/air/payments", {"data": {"order_id": "ord_1", "payment": {
        "type": "balance", "amount": "91.20", "currency": "GBP"}}})  # the exact price you approved
    assert (done["status"], done["reference"]) == ("confirmed", "RZPNX8") and "no real money" in done["payment"]


def test_duffel_price_change_stops_the_payment(duffel):
    calls, order = duffel
    h = b.hold_flight("BLR", "GOI", "2026-11-07", "IndiGo", "21:00", 6411)
    # no IndiGo: Duffel's made-up airline, not a test fare under a real name (British Airways doesn't fly BLR→GOI)
    assert calls[1][2]["data"]["selected_offers"] == ["off_same2"]
    assert h["summary"] == "IndiGo BLR→GOI Sat 07 Nov · Duffel test hold as Duffel Airways"
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


def test_a_stale_duffel_fare_falls_through_to_the_next(duffel, monkeypatch):
    calls, order = duffel
    fake, tried = b._duffel, []

    def stale_first(method, path, body=None):
        if path == "/air/orders" and method == "POST":
            tried.append(body["data"]["selected_offers"][0])
            if len(tried) == 1:
                raise ValueError("Duffel: offer_no_longer_available: Please select another offer")
        return fake(method, path, body)

    monkeypatch.setattr(b, "_duffel", stale_first)
    h = b.hold_flight("BLR", "GOI", "2026-11-07", "Duffel Airways", "21:00", 6411)
    assert tried == ["off_same2", "off_same"] and h["details"]["order_id"] == "ord_1"  # cheapest went stale: next one


def test_an_airline_duffel_never_sells_falls_back_to_another(duffel, monkeypatch):
    """Duffel's test mode never sells some airlines (Air India): the outbound leg is still held, on another airline."""
    calls, order = duffel
    fake, tried = b._duffel, []

    def duffel_airways_sold_out(method, path, body=None):
        if path == "/air/orders" and method == "POST":
            tried.append(body["data"]["selected_offers"][0])
            if body["data"]["selected_offers"][0].startswith("off_same"):
                raise ValueError("Duffel: offer_no_longer_available: Please select another offer")
        return fake(method, path, body)

    monkeypatch.setattr(b, "_duffel", duffel_airways_sold_out)
    h = b.hold_flight("BLR", "GOI", "2026-11-07", "Duffel Airways", "21:00", 6411)
    assert tried == ["off_same2", "off_same", "off_other"]  # the airline you priced first, then the cheapest other
    assert h["summary"] == "Duffel Airways BLR→GOI Sat 07 Nov · Duffel test hold as British Airways"
    assert h["details"]["asked_for"] == "Duffel Airways"


def test_declining_a_duffel_hold_cancels_it_with_duffel(duffel, monkeypatch):
    calls, order = duffel
    fake, cancelled = b._duffel, []

    def with_cancellations(method, path, body=None):
        if path.startswith("/air/order_cancellations"):
            cancelled.append((path, body))
        if path == "/air/order_cancellations":
            return {"id": "ore_1", "refund_amount": "0.00"}
        if path == "/air/order_cancellations/ore_1/actions/confirm":
            return {"id": "ore_1"}
        return fake(method, path, body)

    monkeypatch.setattr(b, "_duffel", with_cancellations)
    h = b.hold_flight("BLR", "GOI", "2026-11-07", "Duffel Airways", "21:00", 6411)
    r = b.release_hold(h["hold_id"])
    assert (r["status"], r["duffel"]) == ("released", "cancelled with Duffel")
    assert cancelled == [("/air/order_cancellations", {"data": {"order_id": "ord_1"}}),
                         ("/air/order_cancellations/ore_1/actions/confirm", None)]
    with pytest.raises(ValueError):
        b.confirm_hold(h["hold_id"])  # a released hold can't be paid any more


def test_the_flight_is_held_in_your_name_from_profile(duffel):
    calls, _ = duffel
    me = {"first_name": "Asha", "last_name": "Rao", "title": "ms", "gender": "f", "born_on": "1999-02-03",
          "email": "asha@example.com", "phone": "+919876543210"}
    ctx = type("C", (), {"request_context": type("R", (), {"meta": type("M", (), {"model_extra": {"traveller": me}})})})
    h = b.hold_flight("BLR", "GOI", "2026-11-07", "Duffel Airways", "21:00", 6411, ctx)
    assert calls[1][2]["data"]["passengers"] == [{"id": "pas_1", "given_name": "Asha", "family_name": "Rao",
                                                  "born_on": "1999-02-03", "title": "ms", "gender": "f",
                                                  "email": "asha@example.com", "phone_number": "+919876543210"}]
    assert h["details"]["booked_for"] == "Passenger: Asha Rao"
    assert "add your details" in b.hold_flight("BLR", "GOI", "2026-11-07", "Duffel Airways", "21:00", 6411)["details"]["booked_for"]
    # the same profile names the hotel guest and the delivery address
    assert b.hold_stay("Goa", "2026-11-07", "2026-11-08", "Vibes Inn", 791, ctx=ctx)["details"]["booked_for"] == "Guest: Asha Rao"
    me |= {"address": "12 MG Road", "city": "Bengaluru", "pincode": "560001"}
    assert b.hold_order("Desk", "Amazon.in", 2599, ctx=ctx)["details"]["booked_for"] == \
        "Deliver to: Asha Rao, 12 MG Road, Bengaluru, 560001, +919876543210"


def test_shopping_and_hotels_land_on_the_stores_checkout():
    o = b.hold_order("Echo Dot", "Amazon.in", 4499, "https://www.amazon.in/Echo-Dot/dp/B09B8XJDW5?ref=x")
    assert o["details"]["checkout"] == "https://www.amazon.in/gp/aws/cart/add.html?ASIN.1=B09B8XJDW5&Quantity.1=1"
    assert b.hold_order("Kettle", "Croma", 999, "https://www.croma.com/p/1")["details"]["checkout"] == "https://www.croma.com/p/1"
    s = b.hold_stay("Goa", "2026-11-07", "2026-11-09", "Vibes Inn", 791)["details"]
    # the hotel's price came from Google Hotels, so that's where it's surely listed (Booking.com may not have it)
    assert (s["store"], s["checkout"]) == ("Google Hotels", "https://www.google.com/travel/search?q=Vibes+Inn%2C+Goa")
    own = b.hold_stay("Goa", "2026-11-07", "2026-11-09", "Vibes Inn", 791, "https://vibesinn.example/book")["details"]
    assert (own["store"], own["checkout"]) == ("the hotel's site", "https://vibesinn.example/book")
    assert "Amazon.in's checkout" in b.confirm_hold(o["hold_id"])["payment"]
