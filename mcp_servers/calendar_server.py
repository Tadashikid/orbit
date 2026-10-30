"""Calendar MCP server on :8101 (streamable HTTP at /mcp).

Reads the Manu demo account's Google Calendar, read-only. Only title, start and end leave this server:
no descriptions, attendees or locations. Falls back to data/calendar.json (source=seeded) when Google is
not signed in or unreachable. Run:  .venv\\Scripts\\python mcp_servers\\calendar_server.py
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from google_auth import creds, token_of

IST = timezone(timedelta(hours=5, minutes=30))  # fixed offset: no DST, and no tzdata needed on Windows
SEEDED = Path(__file__).resolve().parents[1] / "data" / "calendar.json"
READ = ToolAnnotations(readOnlyHint=True)

mcp = FastMCP("calendar", port=8101 + int(os.getenv("ORBIT_PORT_OFFSET", "0")))  # tests use their own ports


def _when(text, end=False):
    """ISO date or datetime -> aware datetime (IST if no offset). A bare END date means the end of that day."""
    dt = datetime.fromisoformat(text)
    if end and len(text) == 10:
        dt += timedelta(days=1)
    return dt if dt.tzinfo else dt.replace(tzinfo=IST)


def _range(start, end):
    s, e = _when(start), _when(end, end=True)
    if e <= s:
        raise ValueError("end must be after start")
    return s, e


def _events(start, end, token=None):
    """Events overlapping [start, end) as (title, start, end), plus source / as_of / note."""
    c = creds(token)
    if c:
        try:
            from googleapiclient.discovery import build

            items = (
                build("calendar", "v3", credentials=c, cache_discovery=False)
                .events()
                .list(calendarId="primary", timeMin=start.isoformat(), timeMax=end.isoformat(), singleEvents=True,
                      orderBy="startTime", maxResults=100, fields="items(summary,start,end,status)")
                .execute()
                .get("items", [])
            )
            when = lambda t: _when(t.get("dateTime") or t["date"])  # noqa: E731  (all-day end dates are exclusive)
            evs = [(i.get("summary", "(no title)"), when(i["start"]), when(i["end"])) for i in items if i.get("status") != "cancelled"]
            return evs, "live", datetime.now(IST).isoformat(timespec="seconds"), None
        except Exception as e:
            note = f"Google Calendar unavailable ({type(e).__name__}); using seeded data"
    else:
        note = "Google not signed in; using seeded data"
    print(note, file=sys.stderr)
    data = json.loads(SEEDED.read_text(encoding="utf-8"))
    evs = [(e["title"], _when(e["start"]), _when(e["end"])) for e in data["events"]]
    return [e for e in evs if e[1] < end and e[2] > start], "seeded", data["as_of"], note


def _meta(source, as_of, note):
    return {"source": source, "as_of": as_of, **({"note": note} if note else {})}


@mcp.tool(annotations=READ)
def list_events(start: str, end: str, ctx: Context = None) -> dict:
    """Events between start and end (ISO date or datetime; IST if no offset). Titles and times only."""
    s, e = _range(start, end)
    evs, *meta = _events(s, e, token_of(ctx))
    return {"events": [{"title": t, "start": a.isoformat(), "end": b.isoformat()} for t, a, b in evs], **_meta(*meta)}


@mcp.tool(annotations=READ)
def find_free_slots(start: str, end: str, min_minutes: int = 60, ctx: Context = None) -> dict:
    """Free gaps of at least min_minutes between start and end, around existing events."""
    s, e = _range(start, end)
    if min_minutes < 1:
        raise ValueError("min_minutes must be at least 1")
    evs, *meta = _events(s, e, token_of(ctx))
    gap = timedelta(minutes=min_minutes)
    slots, cursor = [], s
    for _, busy_start, busy_end in sorted(evs, key=lambda x: x[1]):
        if busy_start - cursor >= gap:
            slots.append((cursor, busy_start))
        cursor = max(cursor, busy_end)
    if e - cursor >= gap:
        slots.append((cursor, e))
    return {
        "slots": [{"start": a.isoformat(), "end": b.isoformat(), "minutes": int((b - a).total_seconds() // 60)} for a, b in slots],
        "busy_events": len(evs),
        **_meta(*meta),
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
