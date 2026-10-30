"""store_firestore.py against the real Firestore project: runs only when FIREBASE_SERVICE_ACCOUNT is set
(FIREBASE_SERVICE_ACCOUNT=firebase-service-account.json pytest tests/test_store_firestore.py). It writes as a
throwaway account and deletes everything it wrote."""
import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not os.getenv("FIREBASE_SERVICE_ACCOUNT"), reason="no Firestore key")
HOLD = {"hold_id": "h1", "kind": "stay", "summary": "Test stay", "amount": 100, "expires_at": "2099-01-01T00:00:00+00:00"}


def test_firestore_keeps_each_account_apart_and_moves_once():
    sys.path.insert(0, str(ROOT / "backend"))
    import store_firestore as fs

    me, other = f"orbit-test-{uuid.uuid4().hex[:8]}@example.com", f"orbit-test-{uuid.uuid4().hex[:8]}@example.com"
    try:
        fs.add_turn(me, "s1", "first?", {"headline": "one"})
        fs.add_turn(me, "s1", "second?", {"headline": "two"})
        assert [t["question"] for t in fs.history(me, "s1")] == ["first?", "second?"]
        assert fs.history(other, "s1") == []

        a = fs.add_action(me, "s1", HOLD)
        assert (a["status"], a["amount"]) == ("pending", 100) and fs.all_actions(other) == []
        assert fs.get_action(other, a["id"]) is None and not fs.move(other, a["id"], "pending", "approving")
        assert fs.move(me, a["id"], "pending", "approving") and not fs.move(me, a["id"], "pending", "approving")
        assert fs.move(me, a["id"], "approving", "confirmed", {"reference": "R1"})
        assert fs.all_actions(me)[0] | {} == fs.get_action(me, a["id"]) and fs.get_action(me, a["id"])["outcome"] == {"reference": "R1"}
    finally:
        for owner in (me, other):
            fs.db.recursive_delete(fs._user(owner))
