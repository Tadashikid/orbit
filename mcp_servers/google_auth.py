"""Google sign-in for the Manu demo account (read-only Calendar + Gmail).

One-time login (opens a browser; YOU sign in, Orbit never sees the password):
    .venv\\Scripts\\python mcp_servers\\google_auth.py
Saves token.json next to credentials.json in the repo root (both gitignored).
Servers call creds(); None means "not signed in" and they fall back to seeded data.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "credentials.json"
TOKEN = ROOT / "token.json"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def creds():
    """Valid read-only credentials, or None. Never opens a browser."""
    if os.getenv("ORBIT_OFFLINE") or not TOKEN.exists():  # ORBIT_OFFLINE=1: force seeded data (tests, save-the-demo)
        return None
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        c = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
        if not c.valid and c.refresh_token:
            c.refresh(Request())
            TOKEN.write_text(c.to_json(), encoding="utf-8")
        return c if c.valid else None
    except Exception as e:  # expired 7-day testing token, revoked access, corrupt file...
        print(f"google_auth: {type(e).__name__}: re-run google_auth.py to sign in again", file=sys.stderr)
        return None


if __name__ == "__main__":
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CLIENT.exists():
        sys.exit(f"Missing {CLIENT}. Download the Desktop OAuth client JSON (docs/GOOGLE_SETUP.md step 5).")
    c = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES).run_local_server(port=0)
    TOKEN.write_text(c.to_json(), encoding="utf-8")
    print(f"Signed in. Saved {TOKEN} (gitignored).")
