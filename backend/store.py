"""Conversation sessions: one SQLite file on this machine (data/session/, gitignored). No accounts yet.

A session is one conversation. Each turn keeps the question and Orbit's answer (verdict + intent, never raw
tool results), so a follow-up like "and the weekend after?" can be understood.
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB = Path(os.getenv("ORBIT_DB") or Path(__file__).resolve().parents[1] / "data" / "session" / "orbit.db")


def _db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS turns (session TEXT, ts TEXT, question TEXT, answer TEXT)")
    return con


def new_session():
    return uuid.uuid4().hex


def add_turn(session, question, answer):
    con = _db()
    with con:
        con.execute("INSERT INTO turns VALUES (?, ?, ?, ?)",
                    (session, datetime.now(timezone.utc).isoformat(timespec="seconds"), question, json.dumps(answer)))
    con.close()


def history(session, limit=6):
    """The last `limit` turns, oldest first: [{"question", "answer"}]."""
    con = _db()
    rows = con.execute("SELECT question, answer FROM turns WHERE session = ? ORDER BY rowid DESC LIMIT ?",
                       (session, limit)).fetchall()
    con.close()
    return [{"question": q, "answer": json.loads(a)} for q, a in reversed(rows)]
