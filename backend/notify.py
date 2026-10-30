"""After you approve a booking, one email: a flight or stay is a calendar invitation (the event + its details), a
shopping order a plain email. Sent by a Google Apps Script web app
(scripts/orbit_notify.gs, deployed in the demo Google account). ORBIT_NOTIFY_URL + ORBIT_NOTIFY_SECRET in .env;
unset = no confirmations, bookings work the same.

Never fails a booking: whatever happens here comes back as one sentence for the card.
"""
import os
from datetime import datetime, timedelta, timezone

import httpx

URL = os.getenv("ORBIT_NOTIFY_URL") or ""
SECRET = os.getenv("ORBIT_NOTIFY_SECRET") or ""
IST = timezone(timedelta(hours=5, minutes=30))
_client = httpx.AsyncClient  # tests swap in a fake Apps Script here
FLIGHT = timedelta(hours=2)  # ponytail: a sandbox fare has no arrival time; Duffel holds carry the real one


def _local(text):
    t = datetime.fromisoformat(text)
    return t if t.tzinfo else t.replace(tzinfo=IST)  # Duffel's departing_at is airport-local; BLR/GOI are IST


def event(booking):
    """The calendar event for a confirmed booking, or None (a shopping order is just the email)."""
    d = booking.get("details") or {}
    if booking["kind"] == "flight":
        start = _local(d["departing_at"]) if d.get("departing_at") else _local(f"{d['date']}T{d.get('depart') or '09:00'}")
        end = _local(d["arriving_at"]) if d.get("arriving_at") else start + FLIGHT
        return {"title": f"✈ {d.get('origin')} → {d.get('dest')} · {d.get('airline', '')} {d.get('flight', '')}".strip(),
                "start": start.isoformat(), "end": end.isoformat(), "all_day": False, "location": f"{d.get('origin')} airport"}
    if booking["kind"] == "stay":
        return {"title": f"\U0001F3E8 {d.get('hotel')}, {d.get('city')}", "all_day": True, "location": d.get("city", ""),
                "start": f"{d['check_in']}T00:00:00+05:30", "end": f"{d['check_out']}T00:00:00+05:30"}
    return None


def message(booking, outcome):
    """(subject, body): the email for an order, the event's description for a flight or stay."""
    lines = [f"Booked: {booking['summary']}", f"Amount: {booking.get('currency', 'INR')} {booking['amount']:,}",
             f"Reference: {outcome.get('reference') or '-'}", outcome.get("payment") or "",
             "", "You approved this in Orbit. Test mode: no real money moved."]
    return f"Booked: {booking['summary']}", "\n".join(lines)


async def _post(payload):
    """One call to the Apps Script -> its JSON answer. Raises on a network error or a non-JSON answer."""
    # Apps Script answers through a redirect to googleusercontent.com, which serves the JSON.
    async with _client(follow_redirects=True, timeout=20) as client:
        return (await client.post(URL, json={"secret": SECRET, **payload})).json()


async def confirm(to, booking, outcome):
    """Email or calendar invitation for one confirmed booking -> {"notice": a sentence for the card, "event_id"}.
    Empty if not set up."""
    if not (URL and SECRET):
        return {}
    subject, body = message(booking, outcome)
    ev = event(booking)
    try:
        r = await _post({"to": to, "subject": subject, "body": body, "event": ev})
    except (httpx.HTTPError, ValueError) as e:
        return {"notice": f"The confirmation email couldn't be sent ({type(e).__name__})."}
    if not r.get("ok"):
        return {"notice": f"The confirmation email couldn't be sent ({str(r.get('error'))[:120]})."}
    if not ev:
        return {"notice": f"Confirmation emailed to {to}."}
    return {"notice": f"Added to your calendar; the invitation with the details went to {to}.", "event_id": r.get("event")}


async def cancel(event_id):
    """Delete a booking's calendar event, without emailing anyone. True if it's gone (or there was none to delete)."""
    if not (URL and SECRET and event_id):
        return True
    try:
        return bool((await _post({"cancel_event": event_id})).get("ok"))
    except (httpx.HTTPError, ValueError):
        return False
