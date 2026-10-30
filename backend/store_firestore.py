"""The same store as store.py, in Firestore: used when FIREBASE_SERVICE_ACCOUNT names a service-account key file.

Everything lives under users/{email}/, so an account's data is one path and a read can't reach another's:
  users/{email}/sessions/{session}/turns/{auto}   a conversation, oldest first by `at`
  users/{email}/actions/{id}                      holds waiting for you, newest first by `at`
  users/{email}/secrets/{name}                    already encrypted by the caller (google_link.py)
Only this backend touches it (the admin key skips security rules); firestore.rules denies every browser.
"""
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import transactional

KEY = Path(__file__).resolve().parents[1] / os.environ["FIREBASE_SERVICE_ACCOUNT"]
db = firestore.client(firebase_admin.initialize_app(credentials.Certificate(KEY), name="orbit-store"))


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")  # sorts as text, and two turns never tie


def _user(owner):
    return db.collection("users").document(owner)


def add_turn(owner, session, question, answer):
    _user(owner).collection("sessions").document(session).collection("turns").add(
        {"at": _now(), "question": question, "answer": json.dumps(answer)})


def history(owner, session, limit=6):
    turns = (_user(owner).collection("sessions").document(session).collection("turns")
             .order_by("at", direction=firestore.Query.DESCENDING).limit(limit).stream())
    return [{"question": t.get("question"), "answer": json.loads(t.get("answer"))} for t in reversed(list(turns))]


def add_action(owner, session, hold):
    action_id = uuid.uuid4().hex
    digest = hashlib.sha256(json.dumps(hold, sort_keys=True).encode()).hexdigest()[:32]
    _user(owner).collection("actions").document(action_id).set(
        {"at": _now(), "session": session, "hold": json.dumps(hold), "hash": digest, "status": "pending", "outcome": None})
    return get_action(owner, action_id)


def _row(doc):
    from store import _action  # store.py imports this module, so not at the top
    d = doc.to_dict()
    return _action((doc.id, d["session"], d["hold"], d["hash"], d["status"], d["outcome"]))


def get_action(owner, action_id):
    doc = _user(owner).collection("actions").document(action_id).get()
    return _row(doc) if doc.exists else None


def all_actions(owner, limit=50):
    docs = _user(owner).collection("actions").order_by("at", direction=firestore.Query.DESCENDING).limit(limit).stream()
    return [_row(d) for d in docs]


def move(owner, action_id, frm, to, outcome=None):
    """Same promise as store.move: in one transaction, so only one of two racing approvals wins."""
    ref = _user(owner).collection("actions").document(action_id)

    @transactional
    def step(tx):
        doc = ref.get(transaction=tx)
        if not doc.exists or doc.get("status") != frm:
            return False
        tx.update(ref, {"status": to, **({"outcome": json.dumps(outcome)} if outcome is not None else {})})
        return True

    return step(db.transaction())


def save_secret(owner, name, value):
    _user(owner).collection("secrets").document(name).set({"value": value})


def secret(owner, name):
    doc = _user(owner).collection("secrets").document(name).get()
    return doc.get("value") if doc.exists else None


def forget_secret(owner, name):
    _user(owner).collection("secrets").document(name).delete()
