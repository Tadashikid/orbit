"""Conversation sessions: one SQLite file on this machine (data/session/, gitignored).

Every row has an owner (the signed-in email) and every read filters on it: one account never sees another's
conversations or bookings, even with the other's session or action id.

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
    con.execute("CREATE TABLE IF NOT EXISTS turns (session TEXT, ts TEXT, question TEXT, answer TEXT, owner TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, session TEXT, ts TEXT, hold TEXT, hash TEXT,"
                " status TEXT, outcome TEXT, owner TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS secrets (owner TEXT, name TEXT, value TEXT, PRIMARY KEY (owner, name))")
    for table in ("turns", "actions"):  # a database from before accounts: its rows were the demo account's
        if "owner" not in {c[1] for c in con.execute(f"PRAGMA table_info({table})")}:
            with con:
                con.execute(f"ALTER TABLE {table} ADD COLUMN owner TEXT")
                con.execute(f"UPDATE {table} SET owner = ?", (os.getenv("ORBIT_DEMO_EMAIL") or "",))
    return con


def new_session():
    return uuid.uuid4().hex


def add_turn(owner, session, question, answer):
    con = _db()
    with con:
        con.execute("INSERT INTO turns VALUES (?, ?, ?, ?, ?)",
                    (session, datetime.now(timezone.utc).isoformat(timespec="seconds"), question, json.dumps(answer), owner))
    con.close()


def history(owner, session, limit=6):
    """`owner`'s last `limit` turns in this session, oldest first: [{"question", "answer"}]."""
    con = _db()
    rows = con.execute("SELECT question, answer FROM turns WHERE session = ? AND owner = ? ORDER BY rowid DESC LIMIT ?",
                       (session, owner, limit)).fetchall()
    con.close()
    return [{"question": q, "answer": json.loads(a)} for q, a in reversed(rows)]


# Pending actions: holds the agent prepared, waiting for the user. Approving one is the only way anything is confirmed.
# The hash pins the exact hold the user saw; status moves pending -> approving -> confirmed in one atomic update each,
# so a double click or a retried request can't confirm twice.
def add_action(owner, session, hold):
    action_id = uuid.uuid4().hex
    digest = hashlib.sha256(json.dumps(hold, sort_keys=True).encode()).hexdigest()[:32]
    con = _db()
    with con:
        con.execute("INSERT INTO actions VALUES (?, ?, ?, ?, ?, 'pending', NULL, ?)",
                    (action_id, session, datetime.now(timezone.utc).isoformat(timespec="seconds"), json.dumps(hold), digest,
                     owner))
    con.close()
    return get_action(owner, action_id)


def get_action(owner, action_id):
    """None for an id that isn't `owner`'s: the same answer as an id that doesn't exist."""
    con = _db()
    row = con.execute("SELECT id, session, hold, hash, status, outcome FROM actions WHERE id = ? AND owner = ?",
                      (action_id, owner)).fetchone()
    con.close()
    return _action(row) if row else None


def move(owner, action_id, frm, to, outcome=None):
    """pending -> approving etc. True only for the one caller that made the move."""
    con = _db()
    with con:
        n = con.execute("UPDATE actions SET status = ?, outcome = COALESCE(?, outcome) WHERE id = ? AND owner = ?"
                        " AND status = ?", (to, json.dumps(outcome) if outcome is not None else None, action_id, owner,
                                            frm)).rowcount
    con.close()
    return n == 1


def _action(row):
    action_id, session, hold, digest, status, outcome = row
    h = json.loads(hold)
    d = h.get("details") or {}
    # Shopping and hotels: the store's checkout (stores have no ordering API, so you pay there yourself).
    link = d.get("checkout") or d.get("link") or ""
    shop = {"store": d.get("store"), "link": link} if h["kind"] in ("order", "stay") and link.startswith("https://") else {}
    shop |= {"booked_for": d["booked_for"]} if d.get("booked_for") else {}
    return {"id": action_id, "session": session, "hold_id": h["hold_id"], "kind": h["kind"], "summary": h["summary"],
            "amount": h["amount"], "currency": h.get("currency", "INR"), "expires_at": h["expires_at"], "hash": digest,
            "status": status, "details": d, **shop,
            **({"outcome": json.loads(outcome)} if outcome else {})}


def all_actions(owner, limit=50):
    """Every one of `owner`'s actions, newest first: what the Bookings window lists."""
    con = _db()
    rows = con.execute("SELECT id, session, hold, hash, status, outcome FROM actions WHERE owner = ? ORDER BY rowid DESC"
                       " LIMIT ?", (owner, limit)).fetchall()
    con.close()
    return [_action(r) for r in rows]



def forget_owner(owner):
    """Delete my data: every conversation, booking card and secret of `owner`."""
    con = _db()
    with con:
        for table in ("turns", "actions", "secrets"):
            con.execute(f"DELETE FROM {table} WHERE owner = ?", (owner,))
    con.close()


# Secrets, one per (owner, name): already encrypted by the caller (google_link.py), stored as they come.
def save_secret(owner, name, value):
    con = _db()
    with con:
        con.execute("INSERT OR REPLACE INTO secrets VALUES (?, ?, ?)", (owner, name, value))
    con.close()


def secret(owner, name):
    con = _db()
    row = con.execute("SELECT value FROM secrets WHERE owner = ? AND name = ?", (owner, name)).fetchone()
    con.close()
    return row[0] if row else None


def forget_secret(owner, name):
    con = _db()
    with con:
        con.execute("DELETE FROM secrets WHERE owner = ? AND name = ?", (owner, name))
    con.close()


# FIREBASE_SERVICE_ACCOUNT set: the same functions, kept in Firestore instead (backend/store_firestore.py).
if os.getenv("FIREBASE_SERVICE_ACCOUNT"):
    from store_firestore import (add_action, add_turn, all_actions, forget_owner, forget_secret,  # noqa: E402,F401,F811
                                 get_action, history, move, save_secret, secret)
