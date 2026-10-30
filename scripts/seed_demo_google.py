"""Put Orbit's demo data into the demo Google account, once: the 15 emails of data/gmail_seeded.json into its inbox
(original senders and dates, unread) and the 22 events of data/calendar.json into its calendar.

    .venv\\Scripts\\python scripts\\seed_demo_google.py

A browser opens: sign in AS THE DEMO ACCOUNT (lokihateshulk@gmail.com) and allow. Needs GOOGLE_CLIENT_ID and
GOOGLE_CLIENT_SECRET in .env, and http://localhost:8765/ as an Authorized redirect URI on that OAuth client.
The permission is used for this run only (no token is saved). Running it again adds nothing twice.
One email is the prompt-injection test on purpose: Orbit must never follow it.
"""
import base64
import hashlib
import json
import os
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

ROOT = Path(__file__).resolve().parents[1]
SCOPES = ["https://www.googleapis.com/auth/gmail.insert", "https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/calendar.events"]


def main():
    load_dotenv(ROOT / ".env")
    client = {"web": {"client_id": os.environ["GOOGLE_CLIENT_ID"], "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                      "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token"}}
    creds = InstalledAppFlow.from_client_config(client, SCOPES).run_local_server(port=8765, open_browser=True)
    gmail, cal = build("gmail", "v1", credentials=creds), build("calendar", "v3", credentials=creds)
    me = gmail.users().getProfile(userId="me").execute()["emailAddress"]
    print(f"Seeding {me}")

    added = 0
    for i, m in enumerate(json.loads((ROOT / "data" / "gmail_seeded.json").read_text(encoding="utf-8"))["emails"]):
        msg_id = f"<orbit-seed-{i}@orbit.example>"  # how a rerun knows it's already there
        if gmail.users().messages().list(userId="me", q=f"rfc822msgid:{msg_id}").execute().get("messages"):
            continue
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"], msg["Message-ID"] = m["from"], me, m["subject"], msg_id
        msg["Date"] = format_datetime(datetime.fromisoformat(m["received"]))
        msg.set_content(m["snippet"])
        gmail.users().messages().insert(userId="me", internalDateSource="dateHeader", body={
            "raw": base64.urlsafe_b64encode(msg.as_bytes()).decode(), "labelIds": ["INBOX", "UNREAD"]}).execute()
        added += 1
    print(f"Inbox: {added} emails added")

    added = 0
    for e in json.loads((ROOT / "data" / "calendar.json").read_text(encoding="utf-8"))["events"]:
        event_id = "orbit" + hashlib.sha1(e["id"].encode()).hexdigest()  # fixed id: a rerun gets 409, not a duplicate
        try:
            cal.events().insert(calendarId="primary", body={
                "id": event_id, "summary": e["title"], "start": {"dateTime": e["start"], "timeZone": "Asia/Kolkata"},
                "end": {"dateTime": e["end"], "timeZone": "Asia/Kolkata"}}).execute()
            added += 1
        except HttpError as err:
            if err.resp.status != 409:
                raise
    print(f"Calendar: {added} events added")


if __name__ == "__main__":
    main()
