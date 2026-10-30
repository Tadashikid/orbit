"""Each Orbit user's own Google Calendar and Gmail: connect once, then Orbit can add events and send emails you approved.

- Connect is Google's OAuth web flow (offline access). The refresh token is encrypted with ORBIT_TOKEN_KEY (Fernet,
  only on this machine) before it's stored under your account (store.py / Firestore): a leaked database alone can't
  read anyone's mail.
- Scopes: add/change calendar events, send mail. Not read your inbox or delete anything.
- Nothing here runs on the model's say-so: the approval endpoint calls send_email / add_event after you tap Approve.
"""
import base64
import json
import os
import time
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

import store

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID") or ""
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET") or ""
KEY = os.getenv("ORBIT_TOKEN_KEY") or ""
# Must match an "Authorized redirect URI" on the OAuth client. The UI's dev server proxies /api to the backend.
REDIRECT = (os.getenv("ORBIT_PUBLIC_URL") or "http://localhost:4173").rstrip("/") + "/api/google/callback"
SCOPES = "openid email https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/gmail.send"
TOKEN_URL = "https://oauth2.googleapis.com/token"
TZ = "Asia/Kolkata"
_access = {}  # owner -> (access token, expires at): an hour's token, kept in memory only


def ready():
    return bool(CLIENT_ID and CLIENT_SECRET and KEY)


def connect_url(state, hint=""):
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": CLIENT_ID, "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPES, "state": state,
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "login_hint": hint})


def _token(**form):
    r = httpx.post(TOKEN_URL, data={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, **form}, timeout=15)
    r.raise_for_status()
    return r.json()


def finish(owner, code):
    """The code Google sent back -> your encrypted refresh token, saved. Returns the Google email you connected."""
    t = _token(code=code, grant_type="authorization_code", redirect_uri=REDIRECT)
    if not t.get("refresh_token"):
        raise ValueError("Google didn't grant offline access")
    # Straight from Google's token endpoint over TLS, so the ID token's claims can be read without re-verifying it.
    claims = json.loads(base64.urlsafe_b64decode(t["id_token"].split(".")[1] + "=="))
    store.save_secret(owner, "google", Fernet(KEY).encrypt(json.dumps(
        {"refresh_token": t["refresh_token"], "email": claims.get("email", "")}).encode()).decode())
    _access[owner] = (t["access_token"], time.time() + t.get("expires_in", 3600) - 60)
    return claims.get("email", "")


def _saved(owner):
    blob = store.secret(owner, "google")
    if not blob or not KEY:
        return None
    try:
        return json.loads(Fernet(KEY).decrypt(blob.encode()))
    except InvalidToken:  # ORBIT_TOKEN_KEY changed: connect again
        return None


def status(owner):
    s = _saved(owner)
    return {"configured": ready(), "connected": bool(s), "email": s["email"] if s else None}


def disconnect(owner):
    s = _saved(owner)
    if s:
        httpx.post("https://oauth2.googleapis.com/revoke", data={"token": s["refresh_token"]}, timeout=15)  # best effort
    store.forget_secret(owner, "google")
    _access.pop(owner, None)


def _bearer(owner):
    token, until = _access.get(owner, (None, 0))
    if time.time() < until:
        return {"Authorization": f"Bearer {token}"}
    s = _saved(owner)
    if not s:
        raise PermissionError("Connect your Google account first (the Google button at the top).")
    t = _token(refresh_token=s["refresh_token"], grant_type="refresh_token")
    _access[owner] = (t["access_token"], time.time() + t.get("expires_in", 3600) - 60)
    return {"Authorization": f"Bearer {t['access_token']}"}


def send_email(owner, to, subject, body):
    msg = EmailMessage()
    msg["To"], msg["Subject"] = ", ".join(to), subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    r = httpx.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", headers=_bearer(owner),
                   json={"raw": raw}, timeout=20)
    r.raise_for_status()
    return {"reference": f"Gmail {r.json()['id']}", "payment": "Sent from your Gmail."}


def add_event(owner, title, start, end, description="", attendees=()):
    event = {"summary": title, "description": description, "start": {"dateTime": start, "timeZone": TZ},
             "end": {"dateTime": end, "timeZone": TZ}, "attendees": [{"email": a} for a in attendees]}
    r = httpx.post("https://www.googleapis.com/calendar/v3/calendars/primary/events", headers=_bearer(owner),
                   params={"sendUpdates": "all" if attendees else "none"}, json=event, timeout=20)
    r.raise_for_status()
    return {"reference": "Google Calendar", "payment": "Added to your calendar.", "link": r.json().get("htmlLink")}
