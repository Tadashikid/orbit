"""Each Orbit user's own Google Calendar and Gmail, read-only: connect once, and Orbit reads your real events and
inbox instead of the sample data.

- Connect is Google's OAuth web flow (offline access). The refresh token is encrypted with ORBIT_TOKEN_KEY (Fernet,
  only on this machine) before it's stored under your account (store.py / Firestore): a leaked database alone can't
  read anyone's mail.
- Scopes: read calendar, read mail. Orbit can't send, change or delete anything.
- The Calendar and Gmail servers get an hour's access token per call, in the MCP request's metadata (never in the
  tool arguments, so it never reaches the model, the trace or the audit log).
"""
import base64
import json
import os
import time
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

import store

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID") or ""
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET") or ""
KEY = os.getenv("ORBIT_TOKEN_KEY") or ""
# Must match an "Authorized redirect URI" on the OAuth client. The UI's dev server proxies /api to the backend.
REDIRECT = (os.getenv("ORBIT_PUBLIC_URL") or "http://localhost:4173").rstrip("/") + "/api/google/callback"
SCOPES = "openid email https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/gmail.readonly"
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


def access_token(owner):
    """An hour's access token for `owner`'s Google, or None if they haven't connected (or it was revoked)."""
    token, until = _access.get(owner, (None, 0))
    if time.time() < until:
        return token
    s = _saved(owner)
    if not s:
        return None
    try:
        t = _token(refresh_token=s["refresh_token"], grant_type="refresh_token")
    except httpx.HTTPError:  # revoked on Google's side, or Google unreachable: read the sample data this time
        return None
    _access[owner] = (t["access_token"], time.time() + t.get("expires_in", 3600) - 60)
    return t["access_token"]
