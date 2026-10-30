"""Booking MCP server on :8106 (streamable HTTP at /mcp). Nothing real is booked, bought or charged.

Flights: with a Duffel TEST token in .env (DUFFEL_ACCESS_TOKEN=duffel_test_...), a flight hold is a real Duffel hold
order in test mode, and confirming pays it from Duffel's test balance. Live tokens are refused: they would buy real
tickets. Without a token, and for hotels and shop orders (Duffel Stays can't hold), it's a local sandbox that
behaves the same way: a hold reserves an exact option at a price until it expires, costs nothing and can be released.
Confirming is the separate, final step.
  hold_flight / hold_stay / hold_order   prepare: the agent may ask for these (Guardian checks each one)
  release_hold                            undo a hold
  confirm_hold                            commit: only Orbit's approval endpoint calls it, after you approve on screen.
                                          Guardian never lets the AI run it. A real provider would hand you its own
                                          checkout here; you pay there, Orbit never sees card details.
Run:  .venv\\Scripts\\python mcp_servers\\booking_server.py
"""
import json
import logging
import os
import secrets
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
logging.getLogger("httpx").setLevel(logging.WARNING)  # request logs would print Duffel URLs; keep them out
IST = timezone(timedelta(hours=5, minutes=30))
DUFFEL = "https://api.duffel.com"
# Duffel needs a named traveller for an order. Test mode only, so a made-up one: never the user's real details.
TEST_TRAVELLER = {"given_name": "Manu", "family_name": "Demo", "born_on": "1998-04-12", "title": "mr", "gender": "m",
                  "email": "manu.demo@example.com", "phone_number": "+442080160508"}
# The session's holds (gitignored). ORBIT_HOLDS points tests at their own file.
HOLDS = Path(os.getenv("ORBIT_HOLDS") or Path(__file__).resolve().parents[1] / "data" / "session" / "holds.json")
HOLD_MINUTES = 30
MAX_PRICE = 1_000_000  # Rs 10 lakh: anything above is a typo or an attack, not a weekend plan
PREPARE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
COMMIT = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)

mcp = FastMCP("booking", port=8106 + int(os.getenv("ORBIT_PORT_OFFSET", "0")))  # tests use their own ports


def _now():
    return datetime.now(IST)


def _load():
    return json.loads(HOLDS.read_text(encoding="utf-8")) if HOLDS.exists() else {}


def _save(holds):
    HOLDS.parent.mkdir(parents=True, exist_ok=True)
    HOLDS.write_text(json.dumps(holds, indent=2, ensure_ascii=False), encoding="utf-8")


def _price(value, what):
    if not isinstance(value, int) or not 0 < value <= MAX_PRICE:
        raise ValueError(f"{what} must be a whole number of rupees between 1 and {MAX_PRICE:,}")
    return value


def _hold(kind, summary, amount, details, currency="INR", expires_at=None):
    holds = _load()
    hold_id = f"h_{secrets.token_hex(6)}"
    expires_at = expires_at or (_now() + timedelta(minutes=HOLD_MINUTES)).isoformat(timespec="seconds")
    holds[hold_id] = {"kind": kind, "summary": summary, "amount": amount, "currency": currency, "details": details,
                      "status": "held", "expires_at": expires_at}
    _save(holds)
    return {"hold_id": hold_id, **holds[hold_id], "sandbox": details.get("provider") != "duffel"}


def _duffel_token():
    """The Duffel token, only if it's a TEST one. A live token would spend real money from Orbit's balance."""
    token = os.getenv("DUFFEL_ACCESS_TOKEN", "").strip()
    return token if token.startswith("duffel_test_") else None


def _duffel(method, path, body=None):
    """One Duffel API call -> its "data". Errors say Duffel's code, never the token."""
    headers = {"Authorization": f"Bearer {_duffel_token()}", "Duffel-Version": "v2", "Accept": "application/json",
               "Content-Type": "application/json", "Accept-Encoding": "gzip"}
    try:
        r = httpx.request(method, f"{DUFFEL}{path}", json=body, headers=headers, timeout=30)
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise ValueError(f"Duffel unreachable ({type(e).__name__})") from None
    if r.status_code >= 400:
        err = (data.get("errors") or [{}])[0]
        raise ValueError(f"Duffel: {err.get('code') or r.status_code}: {str(err.get('message', ''))[:120]}")
    return data["data"]


def _duffel_hold(origin, dest, date, airline):
    """A real Duffel hold order (test mode): the cheapest fare that can be held, the same airline if it's there."""
    request = _duffel("POST", "/air/offer_requests?return_offers=true", {"data": {
        "slices": [{"origin": origin, "destination": dest, "departure_date": date}],
        "passengers": [{"type": "adult"}], "cabin_class": "economy"}})
    holdable = [o for o in request.get("offers", []) if not o["payment_requirements"]["requires_instant_payment"]]
    if not holdable:
        raise ValueError(f"Duffel has no fare from {origin} to {dest} on {date} that can be held. Book it with the airline.")
    cheapest = sorted(holdable, key=lambda o: float(o["total_amount"]))
    same = [o for o in cheapest if o["owner"]["name"].lower() == airline.lower()]
    # Fares go stale between search and order ("offer_no_longer_available"): the airline you priced first, then the
    # cheapest others (Duffel's test mode never sells some airlines, e.g. Air India). The summary names who's held.
    for offer in same[:3] + [o for o in cheapest if o not in same][:3]:
        try:
            order = _duffel("POST", "/air/orders", {"data": {
                "type": "hold", "selected_offers": [offer["id"]],
                "passengers": [{"id": p["id"], **TEST_TRAVELLER} for p in offer["passengers"]]}})
            break
        except ValueError as e:
            if "offer_no_longer_available" not in str(e) and "price_changed" not in str(e):
                raise
    else:
        raise ValueError(f"Duffel's fares from {origin} to {dest} on {date} kept selling out. Try again in a minute.")
    owner = offer["owner"]["name"]
    legs = (order.get("slices") or [{}])[0].get("segments") or [{}]  # the times and flight number, for the calendar
    carrier = legs[0].get("marketing_carrier") or {}
    summary = f"{owner} {origin}→{dest} {Date.fromisoformat(date):%a %d %b} · Duffel test"
    return _hold("flight", summary, float(order["total_amount"]), {
        "provider": "duffel", "order_id": order["id"], "offer_id": offer["id"], "airline": owner, "asked_for": airline,
        "origin": origin, "dest": dest, "date": date, "total_amount": order["total_amount"],
        "total_currency": order["total_currency"], "departing_at": legs[0].get("departing_at"),
        "arriving_at": legs[-1].get("arriving_at"),
        "flight": f"{carrier.get('iata_code', '')}{legs[0].get('marketing_carrier_flight_number', '')}"},
        currency=order["total_currency"], expires_at=order["payment_status"]["payment_required_by"])


def _duffel_pay(h):
    """Pay a Duffel hold from the test balance, at the price the user approved. A changed price stops it."""
    d = h["details"]
    order = _duffel("GET", f"/air/orders/{d['order_id']}")
    if (order["total_amount"], order["total_currency"]) != (d["total_amount"], d["total_currency"]):
        raise ValueError(f"price changed to {order['total_currency']} {order['total_amount']} since you approved "
                         f"{d['total_currency']} {d['total_amount']}. Look at it again.")
    _duffel("POST", "/air/payments", {"data": {"order_id": d["order_id"], "payment": {
        "type": "balance", "amount": order["total_amount"], "currency": order["total_currency"]}}})
    return _duffel("GET", f"/air/orders/{d['order_id']}").get("booking_reference") or order.get("booking_reference")


@mcp.tool(annotations=PREPARE)
def hold_flight(origin: str, dest: str, date: str, airline: str, depart: str, price: int) -> dict:
    """Hold one flight (an exact fare from search_flights). Free, reversible, nothing is paid.
    date is YYYY-MM-DD, depart is HH:MM, price in whole rupees. With a Duffel test token this is a Duffel hold order
    (its fare and deadline); otherwise a 30-minute sandbox hold at the given price."""
    day = Date.fromisoformat(date)
    if _duffel_token():
        return _duffel_hold(origin.upper(), dest.upper(), date, airline)
    summary = f"{airline} {origin.upper()}→{dest.upper()} {day:%a %d %b} {depart}"
    return _hold("flight", summary, _price(price, "price"),
                 {"origin": origin.upper(), "dest": dest.upper(), "date": date, "airline": airline, "depart": depart})


@mcp.tool(annotations=PREPARE)
def hold_stay(city: str, check_in: str, check_out: str, hotel: str, per_night: int) -> dict:
    """Hold a hotel stay (an exact hotel from search_hotels) for 30 minutes. Free, reversible, nothing is paid.
    Dates are YYYY-MM-DD; per_night in whole rupees."""
    nights = (Date.fromisoformat(check_out) - Date.fromisoformat(check_in)).days
    if not 1 <= nights <= 30:
        raise ValueError("check_out must be 1 to 30 nights after check_in")
    amount = _price(per_night, "per_night") * nights
    summary = f"{hotel}, {city} · {nights} night{'s' if nights > 1 else ''} from {Date.fromisoformat(check_in):%a %d %b}"
    return _hold("stay", summary, amount,
                 {"city": city, "check_in": check_in, "check_out": check_out, "hotel": hotel, "per_night": per_night})


@mcp.tool(annotations=PREPARE)
def hold_order(item: str, store: str, price: int, link: str = "") -> dict:
    """Put one product (an exact offer from check_price) in a cart for 30 minutes. Free, reversible, nothing is paid."""
    return _hold("order", f"{item[:80]} from {store}", _price(price, "price"),
                 {"item": item[:200], "store": store, "link": link[:500]})


@mcp.tool(annotations=PREPARE)
def release_hold(hold_id: str) -> dict:
    """Let a hold go. Nothing was paid, so there is nothing to refund."""
    # ponytail: a Duffel hold is only marked released here and lapses at its payment deadline; cancel it through
    # /air/order_cancellations if seats held for days start to matter.
    holds = _load()
    if holds.get(hold_id, {}).get("status") != "held":
        raise ValueError(f"no active hold {hold_id}")
    holds[hold_id]["status"] = "released"
    _save(holds)
    return {"hold_id": hold_id, "status": "released"}


@mcp.tool(annotations=COMMIT)
def confirm_hold(hold_id: str) -> dict:
    """Confirm a hold. Only Orbit's approval endpoint calls this, after the user approves it on screen."""
    holds = _load()
    h = holds.get(hold_id)
    if not h:
        raise ValueError(f"no hold {hold_id}")
    if h["status"] == "confirmed":  # idempotent: a retried approval doesn't book twice
        return {"hold_id": hold_id, **h}
    if h["status"] != "held":
        raise ValueError(f"hold {hold_id} is {h['status']}")
    if datetime.fromisoformat(h["expires_at"]) <= _now():
        h["status"] = "expired"
        _save(holds)
        raise ValueError(f"hold {hold_id} expired")
    if h["details"].get("provider") == "duffel":
        reference = _duffel_pay(h)  # raises on a changed price: the hold stays, nothing is paid
        h.update(status="confirmed", reference=reference, confirmed_at=_now().isoformat(timespec="seconds"),
                 payment="Duffel test mode: paid from Duffel's test balance, no real money. Live, you'd pay at checkout.")
        _save(holds)
        return {"hold_id": hold_id, **h}
    h.update(status="confirmed", reference=f"ORB-{secrets.token_hex(3).upper()}",
             confirmed_at=_now().isoformat(timespec="seconds"),
             payment="Sandbox: nothing was charged. A real provider would open its own checkout here for you to pay.")
    _save(holds)
    return {"hold_id": hold_id, **h}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
