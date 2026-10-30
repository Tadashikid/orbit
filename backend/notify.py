"""After you approve a booking: a confirmation email and a calendar event, through a Google Apps Script web app
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
                "start": start.isoformat(), "end": end.isoformat(), "all_day": False, "location": f"{d.get('origin')} airport",
                "description": booking["summary"]}
    if booking["kind"] == "stay":
        return {"title": f"\U0001F3E8 {d.get('hotel')}, {d.get('city')}", "all_day": True, "location": d.get("city", ""),
                "start": f"{d['check_in']}T00:00:00+05:30", "end": f"{d['check_out']}T00:00:00+05:30",
                "description": booking["summary"]}
    return None


def message(booking, outcome):
    """(subject, body) of the confirmation email."""
    lines = [f"Booked: {booking['summary']}", f"Amount: {booking.get('currency', 'INR')} {booking['amount']:,}",
             f"Reference: {outcome.get('reference') or '-'}", outcome.get("payment") or "",
             "", "You approved this in Orbit. Test mode: no real money moved."]
    return f"Booked: {booking['summary']}", "\n".join(lines)


async def confirm(to, booking, outcome):
    """Email + calendar event for one confirmed booking. Returns a sentence for the card, or None if not set up."""
    if not (URL and SECRET):
        return None
    subject, body = message(booking, outcome)
    ev = event(booking)
    try:
        # Apps Script answers through a redirect to googleusercontent.com, which serves the JSON.
        async with _client(follow_redirects=True, timeout=20) as client:
            r = (await client.post(URL, json={"secret": SECRET, "to": to, "subject": subject, "body": body, "event": ev})).json()
    except (httpx.HTTPError, ValueError) as e:
        return f"The confirmation email couldn't be sent ({type(e).__name__})."
    if not r.get("ok"):
        return f"The confirmation email couldn't be sent ({str(r.get('error'))[:120]})."
    return f"Confirmation emailed to {to}" + (" and added to your calendar." if ev else ".")
