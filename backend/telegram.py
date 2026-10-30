"""Booking alerts on Telegram: anyone who scans Orbit's QR and taps Start gets the same message as the WhatsApp one.

TELEGRAM_BOT_TOKEN in .env (from @BotFather). Unset = no Telegram. Linking: the app asks for a one-time link
(t.me/<bot>?start=<code>, 10 minutes); tapping Start sends the bot "/start <code>"; Orbit reads the bot's messages from
Telegram (getUpdates: no public URL needed) and saves that chat to the account. Up to MAX_CHATS chats per account.
Never fails a booking: whatever happens is one sentence for the card.
"""
import json
import os
import re
import secrets
import time

import httpx

import store

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or ""
MAX_CHATS = 5  # you plus a few judges
CODE_TTL_S = 600
_client = httpx.AsyncClient  # tests swap in a fake Telegram here
_codes = {}  # one-time code -> (owner, expires at). ponytail: in memory: a restart means asking for a new QR
_state = {"offset": 0, "username": None}


def ready():
    return bool(TOKEN)


async def _call(method, **params):
    async with _client(timeout=15) as client:
        data = (await client.post(f"https://api.telegram.org/bot{TOKEN}/{method}", json=params)).json()
    if not data.get("ok"):
        raise ValueError(data.get("description") or "Telegram said no")
    return data["result"]


def chats(owner):
    return json.loads(store.secret(owner, "telegram") or "[]")


async def link(owner):
    """A one-time t.me link that ties the Telegram chat that opens it to `owner`."""
    if not _state["username"]:
        _state["username"] = (await _call("getMe"))["username"]
    now = time.time()
    for code in [c for c, (_, until) in _codes.items() if until < now]:
        del _codes[code]
    code = secrets.token_urlsafe(12)
    _codes[code] = (owner, now + CODE_TTL_S)
    return f"https://t.me/{_state['username']}?start={code}"


async def sync():
    """Read what people sent the bot since last time: a valid "/start <code>" links that chat to the code's account."""
    updates = await _call("getUpdates", offset=_state["offset"], timeout=0, allowed_updates=["message"])
    for u in updates:
        _state["offset"] = u["update_id"] + 1
        msg = u.get("message") or {}
        chat, text = (msg.get("chat") or {}).get("id"), msg.get("text") or ""
        if not chat or not text.startswith("/start"):
            continue  # anything else people type is ignored: the bot only sends alerts
        m = re.fullmatch(r"/start (\S+)", text.strip())
        owner, until = _codes.pop(m[1], (None, 0)) if m else (None, 0)
        if owner and until >= time.time():
            linked = [c for c in chats(owner) if c != chat][-(MAX_CHATS - 1):] + [chat]
            store.save_secret(owner, "telegram", json.dumps(linked))
            reply = "✅ Linked to Orbit. You'll get a message here for each booking that's confirmed or cancelled."
        else:
            reply = "This link has expired or was already used. In Orbit, open Bookings and scan the Telegram QR again."
        await _call("sendMessage", chat_id=chat, text=reply)


async def send(owner, body):
    """Send `body` to every chat linked to `owner`. A sentence for the card, or None if Telegram isn't set up or linked."""
    targets = chats(owner) if TOKEN and owner else []
    if not targets:
        return None
    sent = 0
    for chat in targets:
        try:
            await _call("sendMessage", chat_id=chat, text=body)
            sent += 1
        except (httpx.HTTPError, ValueError):
            pass  # that person blocked the bot, or Telegram is down: the others still get it
    if not sent:
        return "The Telegram alert couldn't be sent."
    return f"Telegram sent to {sent} chat{'s' if sent > 1 else ''}."
