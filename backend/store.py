"""Conversation sessions: one SQLite file on this machine (data/session/, gitignored). No accounts yet.

A session is one conversation. Each turn keeps the question and Orbit's answer (verdict + intent, never raw
tool results), so a follow-up like "and the weekend after?" can be understood.
"""
import hashlib
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
    con.execute("CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, session TEXT, ts TEXT, hold TEXT, hash TEXT,"
                " status TEXT, outcome TEXT)")
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


# Pending actions: holds the agent prepared, waiting for the user. Approving one is the only way anything is confirmed.
# The hash pins the exact hold the user saw; status moves pending -> approving -> confirmed in one atomic update each,
# so a double click or a retried request can't confirm twice.
def add_action(session, hold):
    action_id = uuid.uuid4().hex
    digest = hashlib.sha256(json.dumps(hold, sort_keys=True).encode()).hexdigest()[:32]
    con = _db()
    with con:
        con.execute("INSERT INTO actions VALUES (?, ?, ?, ?, ?, 'pending', NULL)",
                    (action_id, session, datetime.now(timezone.utc).isoformat(timespec="seconds"), json.dumps(hold), digest))
    con.close()
    return get_action(action_id)


def get_action(action_id):
    con = _db()
    row = con.execute("SELECT id, session, hold, hash, status, outcome FROM actions WHERE id = ?", (action_id,)).fetchone()
    con.close()
    return _action(row) if row else None


def actions(session):
    con = _db()
    rows = con.execute("SELECT id, session, hold, hash, status, outcome FROM actions WHERE session = ? ORDER BY rowid",
                       (session,)).fetchall()
    con.close()
    return [_action(r) for r in rows]


def move(action_id, frm, to, outcome=None):
    """pending -> approving etc. True only for the one caller that made the move."""
    con = _db()
    with con:
        n = con.execute("UPDATE actions SET status = ?, outcome = COALESCE(?, outcome) WHERE id = ? AND status = ?",
                        (to, json.dumps(outcome) if outcome is not None else None, action_id, frm)).rowcount
    con.close()
    return n == 1


def _action(row):
    action_id, session, hold, digest, status, outcome = row
    h = json.loads(hold)
    return {"id": action_id, "session": session, "hold_id": h["hold_id"], "kind": h["kind"], "summary": h["summary"],
            "amount": h["amount"], "expires_at": h["expires_at"], "hash": digest, "status": status,
            **({"outcome": json.loads(outcome)} if outcome else {})}
