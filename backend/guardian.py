"""Guardian: every tool call is checked here, in code, before it runs. A prompt is not a security boundary.

- Only tools discovered from a plugged-in server can run (no invented tool names).
- Only tools on Orbit's own POLICY list can run. A server's readOnlyHint is the server describing itself,
  so it can make a tool stricter, never looser.
- Write tools never run on the model's say-so: only the user can approve a change, through the UI.
  Neither the model nor anything it read (emails, events) can approve it.
- Outbound tools (they send their arguments to a third party) can't carry private data: numbers and emails
  read from your private sources are blocked from their arguments, unless you typed them in the question.
- Each question has a call budget, so a looping model can't burn SerpAPI credits.
- Holds (prepare) only after the engine cleared a plan in the same request; confirming or paying (commit) never
  runs from the model: only the approval endpoint does that, after the user approves on screen.
- Every decision is appended to an audit log on this machine.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

# private: reads your data, which stays here. outbound: sends its args to a third party (SerpAPI, costs credits).
# write: changes data, only you can approve it. plan: Orbit's own check_plan, which runs the whole read pipeline
# (may hit SerpAPI) and returns your numbers, so it is budgeted and leak-checked like outbound, remembered like private.
# A tool that isn't listed doesn't run.
POLICY = {
    "orbit__check_plan": "plan",
    "calendar__list_events": "private", "calendar__find_free_slots": "private",
    "gmail__list_tasks": "private", "gmail__get_deadlines": "private",
    "finance__get_balance": "private", "finance__get_sips": "private",
    "finance__get_spending_summary": "private", "finance__get_cost_table": "private",
    "finance__load_statement": "write",
    "travel__search_flights": "outbound", "travel__search_hotels": "outbound",
    "price__check_price": "outbound",
    # prepare: reversible holds (no money moves). Only after the engine cleared a plan in this same goal.
    "booking__hold_flight": "prepare", "booking__hold_stay": "prepare", "booking__hold_order": "prepare",
    "booking__release_hold": "prepare",
    # commit: confirming / paying. Never from the model: only Orbit's approval endpoint, after you approve on screen.
    "booking__confirm_hold": "commit", "booking__cancel_booking": "commit",
}
MAX_CALLS = 24  # per question; a trip needs ~8
MAX_OUTBOUND = 8  # per question; a trip needs 3
MAX_HOLDS = 4  # per goal: a flight out, a flight back, a stay, one spare
CLEARS = {"yes", "yes_with_conditions", "risky"}  # engine verdicts that let the agent put a plan on hold
AUDIT_LOG = Path(os.getenv("ORBIT_AUDIT_LOG") or Path(__file__).resolve().parents[1] / "data" / "session" / "audit.jsonl")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
WRITE = "write tool: only you can approve this, not the AI"
COMMIT = "confirming or paying: only you can approve this, on screen in Orbit"


class Guard:
    """One per question: counts calls and remembers what was read privately, so it can't leave."""

    def __init__(self, catalogue, question=""):
        self.tools = {t["name"]: t for t in catalogue}
        self.typed = question.replace(",", "")  # what the user said themselves is theirs to send
        self.secrets = set()
        self.calls = self.outbound = self.holds = 0
        self.cleared = False  # set once the engine says yes / yes_with_conditions / risky to a plan in this goal

    def check(self, name, args=None):
        """("allowed" | "blocked" | "needs_approval", reason). An allowed answer counts against the budget."""
        tool, kind = self.tools.get(name), POLICY.get(name)
        if tool is None:
            return "blocked", "not a tool from a plugged-in server"
        if kind is None:
            return "blocked", "not on Orbit's reviewed tool list"
        if kind == "commit":
            return "needs_approval", COMMIT
        if kind == "write" or tool.get("destructive") or (kind != "prepare" and not tool["read_only"]):
            return "needs_approval", WRITE
        if self.calls >= MAX_CALLS:
            return "blocked", f"call budget used up ({MAX_CALLS} per question)"
        if kind == "prepare":
            if not self.cleared:
                return "blocked", "check the plan with your budget first: Orbit only holds what its engine says fits"
            if self.holds >= MAX_HOLDS:
                return "blocked", f"hold limit reached ({MAX_HOLDS} per request)"
            # Names, not prices: a fare's price came from the plan itself, but free text must not carry your data.
            if self._leaks({k: v for k, v in (args or {}).items() if isinstance(v, str)}):
                return "blocked", "would send your private data to a third party"
            self.holds += 1
        if kind in ("outbound", "plan"):
            if self.outbound >= MAX_OUTBOUND:
                return "blocked", f"outside-search budget used up ({MAX_OUTBOUND} per question)"
            # ponytail: literal match only; a model spelling digits out ("five four...") gets past. Fine while the
            # only outbound tools are searches; add an allowlist of arg shapes once a tool can send free text.
            if self._leaks(args):
                return "blocked", "would send your private data to a third party"
            self.outbound += 1
        self.calls += 1
        return "allowed", ""

    def _leaks(self, args):
        sent = json.dumps(args or {}).replace(",", "")
        return any(re.search(rf"(?<![\w.-]){re.escape(s)}(?![\w.-])", sent) for s in self.secrets)

    def saw(self, result):
        """Remember the numbers (>= 1000) and emails a private read returned."""
        if not result.get("ok") or POLICY.get(f"{result['server']}__{result['tool']}") not in ("private", "plan"):
            return
        found = set()

        def walk(v):
            if isinstance(v, dict):
                for x in v.values():
                    walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)
            elif isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) >= 1000:
                found.add(str(int(v)) if v == int(v) else str(v))
            elif isinstance(v, str):
                found.update(EMAIL.findall(v))

        walk(result.get("result"))
        self.secrets |= {s for s in found if s not in self.typed}
        verdict = (result.get("result") or {}).get("verdict")
        # A "yes" with Finance off only means the calendar is free: holds need the money checked too.
        if isinstance(verdict, dict) and verdict.get("verdict") in CLEARS and (verdict.get("numbers") or {}).get("balance") is not None:
            self.cleared = True


def check(name, catalogue, args=None):
    """One-off check, without a question's budget or memory."""
    return Guard(catalogue).check(name, args)


def audit(question, trace):
    """Append this question's decisions to the local audit log. Results are not logged, only what ran and why."""
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "question": question,
           "calls": [{k: t.get(k) for k in ("server", "tool", "args", "by", "guardian", "error")} for t in trace]}
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
