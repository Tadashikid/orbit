"""Booking MCP server on :8106 (streamable HTTP at /mcp). A SANDBOX: nothing real is booked, bought or charged.

It behaves like a real provider's hold (a Duffel hold order, a shop cart): a hold reserves an exact option at a price
until it expires, costs nothing and can be released. Confirming is the separate, final step.
  hold_flight / hold_stay / hold_order   prepare: the agent may ask for these (Guardian checks each one)
  release_hold                            undo a hold
  confirm_hold                            commit: only Orbit's approval endpoint calls it, after you approve on screen.
                                          Guardian never lets the AI run it. A real provider would hand you its own
                                          checkout here; you pay there, Orbit never sees card details.
Run:  .venv\\Scripts\\python mcp_servers\\booking_server.py
"""
import json
import os
import secrets
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

IST = timezone(timedelta(hours=5, minutes=30))
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


def _hold(kind, summary, amount, details):
    holds = _load()
    hold_id = f"h_{secrets.token_hex(6)}"
    holds[hold_id] = {"kind": kind, "summary": summary, "amount": amount, "details": details, "status": "held",
                      "expires_at": (_now() + timedelta(minutes=HOLD_MINUTES)).isoformat(timespec="seconds")}
    _save(holds)
    return {"hold_id": hold_id, **holds[hold_id], "sandbox": True}


@mcp.tool(annotations=PREPARE)
def hold_flight(origin: str, dest: str, date: str, airline: str, depart: str, price: int) -> dict:
    """Hold one flight (an exact fare from search_flights) for 30 minutes. Free, reversible, nothing is paid.
    date is YYYY-MM-DD, depart is HH:MM, price in whole rupees."""
    day = Date.fromisoformat(date)
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
    h.update(status="confirmed", reference=f"ORB-{secrets.token_hex(3).upper()}",
             confirmed_at=_now().isoformat(timespec="seconds"),
             payment="Sandbox: nothing was charged. A real provider would open its own checkout here for you to pay.")
    _save(holds)
    return {"hold_id": hold_id, **h}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
