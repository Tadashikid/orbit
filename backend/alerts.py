"""Booking alerts on your phone, through Twilio: one WhatsApp message (or SMS) when a booking is confirmed or cancelled.

.env: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM (the sandbox / trial number), ORBIT_ALERTS=whatsapp (default)
or sms. Unset = no alerts; bookings work the same. Never fails a booking: whatever happens is one sentence for the card.
"""
import os
import re
from datetime import datetime

import httpx

SID = os.getenv("TWILIO_ACCOUNT_SID") or ""
TOKEN = os.getenv("TWILIO_AUTH_TOKEN") or ""
FROM = (os.getenv("TWILIO_FROM") or "").replace("whatsapp:", "").strip()
CHANNEL = "sms" if (os.getenv("ORBIT_ALERTS") or "").lower() == "sms" else "whatsapp"
_client = httpx.AsyncClient  # tests swap in a fake Twilio here


def phone(text):
    """Your number as +<country><number>, or None. Ten digits without a code are taken as Indian (+91)."""
    digits = re.sub(r"[\s()-]", "", text or "")
    if re.fullmatch(r"[6-9]\d{9}", digits):
        digits = "+91" + digits
    return digits if re.fullmatch(r"\+[1-9]\d{7,14}", digits) else None


def _money(a):
    return f"Rs {a['amount']:,}" if a.get("currency", "INR") == "INR" else f"{a['currency']} {a['amount']:,.2f}"


def confirmed(a, booking):
    """The message for a booking you approved: what, when, the provider's reference and Orbit's id."""
    d = booking.get("details") or {}
    when = f" · departs {datetime.fromisoformat(d['departing_at']):%a %d %b %H:%M}" if d.get("departing_at") else ""
    return (f"Orbit: Booking confirmed ✅\n{a['summary']}{when}\nRef {booking.get('reference') or '-'} · "
            f"Orbit ID {a['id'][:8]} · {_money(a)}")


def cancelled(a):
    return (f"Orbit: Booking cancelled ❌\n{a['summary']}\nOrbit ID {a['id'][:8]} · {_money(a)} held, "
            f"nothing was charged")


async def send(to, body):
    """Text `body` to `to` (+91...). Returns a sentence for the card, or None if alerts aren't set up or no phone."""
    if not (SID and TOKEN and FROM and to):
        return None
    prefix = "whatsapp:" if CHANNEL == "whatsapp" else ""
    try:
        async with _client(timeout=15) as client:
            r = await client.post(f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json", auth=(SID, TOKEN),
                                  data={"From": prefix + FROM, "To": prefix + to, "Body": body})
        r.raise_for_status()
    except httpx.HTTPStatusError as e:  # Twilio's reason, e.g. a phone that hasn't joined the sandbox
        try:
            why = e.response.json().get("message", "")
        except ValueError:
            why = ""
        return f"The {CHANNEL} alert couldn't be sent ({why[:120] or e.response.status_code})."
    except httpx.HTTPError as e:
        return f"The {CHANNEL} alert couldn't be sent ({type(e).__name__})."
    return f"{'WhatsApp' if CHANNEL == 'whatsapp' else 'Text'} sent to your phone (ending {to[-4:]})."
