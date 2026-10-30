"""Orbit API on 127.0.0.1:8000. Needs the MCP servers running (run_servers.py).

    .venv\\Scripts\\python backend\\main.py

POST /login {"email", "password"}     -> sets the demo session cookie; every endpoint below needs it (401 otherwise)
POST /logout, GET /me                  -> sign out; who is signed in
GET  /actions                          -> every booking the agent prepared, newest first (expired holds marked)
POST /actions/{id}/approve {"hash"}    -> confirm a hold the agent prepared (sandbox: nothing is charged)
POST /actions/{id}/decline             -> let it go
POST /ask {"question", "session_id"?}  -> {"verdict", "explanation", "trace", "planner", "model", "offline", "session_id"}
POST /agent {"goal", "session_id"?}    -> server-sent events: session, tool, step, message, done (the agent loop)
GET  /servers                          -> every server: plugged in or not, reachable, and its discovered tools
POST /servers/{name}/plug | /unplug    -> the hot-plug (the UI's On / Off)
POST /statement {"csv": "..."}         -> upload a bank statement: masked here, in memory, then handed to Finance
POST /statement {"sample": "name"}     -> the same with one of data/samples/*.csv (demo budgets)
GET  /statement, GET /statement/samples -> balance + spending summary of the loaded statement; the sample names
GET  /balance                          -> the balance from the uploaded statement (needs Finance plugged in)

/ask: Gemini decides which tools to read (rules planner if no model answers); Guardian checks every call;
the canonical reads the money rule needs are filled in if the model skipped them; engine.py decides;
Gemini explains. The verdict numbers only ever come from the engine.
"""
import asyncio
import hashlib
import hmac
import json
import os
import re
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import agent  # noqa: E402  (reads GEMINI_* from .env)
import engine  # noqa: E402
import guardian  # noqa: E402
import planner  # noqa: E402
import statement_import  # noqa: E402
import store  # noqa: E402
from registry import SERVERS, Registry  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
TODAY = date.fromisoformat(os.getenv("ORBIT_TODAY") or date.today().isoformat())  # frozen demo clock (PLAN P2)
GEMINI = agent.make_generate()  # None without GEMINI_API_KEY -> rules planner only

app = FastAPI(title="Orbit")
registry = Registry(plugged=("calendar", "gmail", "travel", "price", "booking"))  # ponytail: one shared registry = one user (demo)

# Demo login: one account from .env, a signed httpOnly cookie, every other endpoint behind it. No password set = no way in.
# ponytail: one hard-coded user, no rate limit; swap for real accounts (Google sign-in / Firebase) before sharing a link.
DEMO_EMAIL = (os.getenv("ORBIT_DEMO_EMAIL") or "lokihateshulk@gmail.com").strip().lower()
DEMO_PASSWORD = os.getenv("ORBIT_DEMO_PASSWORD") or ""
COOKIE = "orbit_session"
_KEY = hashlib.sha256(f"orbit-session:{DEMO_PASSWORD}".encode()).digest()  # a new password signs everyone out
OPEN = {"/login", "/logout", "/me"}


def _signed(email):
    return f"{email}.{hmac.new(_KEY, email.encode(), 'sha256').hexdigest()}"


def _user(request: Request):
    value = request.cookies.get(COOKIE, "")
    email = value.rpartition(".")[0]
    return email if DEMO_PASSWORD and email and hmac.compare_digest(value.encode(), _signed(email).encode()) else None


@app.middleware("http")
async def signed_in_only(request: Request, call_next):
    if request.url.path not in OPEN and not _user(request):
        return JSONResponse({"detail": "Sign in first"}, status_code=401)
    return await call_next(request)


class Login(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


@app.post("/login")
def login(body: Login, response: Response):
    if not DEMO_PASSWORD:
        raise HTTPException(503, "Demo login isn't set up: add ORBIT_DEMO_PASSWORD to .env")
    email_ok = hmac.compare_digest(body.email.strip().lower().encode(), DEMO_EMAIL.encode())
    password_ok = hmac.compare_digest(body.password.encode(), DEMO_PASSWORD.encode())
    if not (email_ok and password_ok):
        raise HTTPException(401, "Wrong email or password")
    response.set_cookie(COOKIE, _signed(DEMO_EMAIL), httponly=True, samesite="strict", max_age=7 * 24 * 3600)
    return {"email": DEMO_EMAIL}


@app.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/me")
def me(request: Request):
    email = _user(request)
    if not email:
        raise HTTPException(401, "Sign in first")
    return {"email": email}


SESSION_ID = r"^[0-9a-f]{32}$"


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=300)
    session_id: str | None = Field(None, pattern=SESSION_ID)  # continue a conversation; omit to start one


class Goal(BaseModel):
    goal: str = Field(min_length=3, max_length=500)
    session_id: str | None = Field(None, pattern=SESSION_ID)


class Statement(BaseModel):
    csv: str | None = Field(None, min_length=10, max_length=2_000_000)
    sample: str | None = Field(None, pattern=r"^[a-z0-9_]{1,60}$")  # a file name in data/samples, nothing else


async def _finance(tool, args=None):
    """User actions on the Finance server. Never reachable from the model's tool loop."""
    if "finance" not in registry.plugged:
        raise HTTPException(409, "Plug in Finance first")
    r = await registry.call(f"finance__{tool}", args)
    if not r["ok"]:
        raise HTTPException(502, r["error"])
    return r["result"]


@app.get("/balance")
async def get_balance():
    return await _finance("get_balance")


async def _summary():
    """What the UI shows about the loaded statement: monthly spend by category, commitments and the forecast."""
    s = await _finance("get_spending_summary", {"days": 30})
    keep = ("monthly_avg_spend", "monthly_avg_by_category", "monthly_commitments", "recurring", "forecast", "as_of")
    return {k: s.get(k) for k in keep}


@app.get("/statement")
async def get_statement():
    """The loaded statement's balance and summary; null while Finance is off or no statement is loaded yet."""
    if "finance" not in registry.plugged:
        return None
    r = await registry.call("finance__get_balance")
    return {**r["result"], "summary": await _summary()} if r["ok"] else None


@app.get("/statement/samples")
def statement_samples():
    return {"samples": sorted(p.stem for p in SAMPLES.glob("*.csv"))}


@app.post("/statement")
async def upload_statement(body: Statement):
    """You uploading the file IS the approval Guardian requires for Finance's load_statement write tool.
    The raw file is masked in memory and never stored; Finance only ever receives date/category/debit/credit/balance."""
    if body.sample:
        path = SAMPLES / f"{body.sample}.csv"
        if not path.is_file():
            raise HTTPException(404, f"no sample statement '{body.sample}'")
        text = path.read_text(encoding="utf-8")
    elif body.csv:
        text = body.csv
    else:
        raise HTTPException(422, "send a csv or the name of a sample")
    try:
        masked, receipt = statement_import.mask_text(text)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    loaded = await _finance("load_statement", {"statement": masked})
    return {"receipt": receipt, **loaded, "summary": await _summary()}


@app.get("/servers")
async def servers():
    """Every server Orbit knows: plugged in (On) or not, reachable, and the tools it announced over tools/list."""
    catalogue = await registry.discover()
    tools = defaultdict(list)
    for t in catalogue["tools"]:
        tools[t["server"]].append({"name": t["tool"], "description": t["description"], "read_only": t["read_only"]})
    status = lambda n: "error" if n in catalogue["offline"] else "connected" if n in registry.plugged else "off"  # noqa: E731
    return {"servers": [{"name": n, "plugged": n in registry.plugged, "status": status(n), "tools": tools[n],
                         **({"error": catalogue["offline"][n]} if n in catalogue["offline"] else {})} for n in SERVERS],
            "today": TODAY.isoformat()}


def _known(name):
    if name not in SERVERS:
        raise HTTPException(404, f"unknown server '{name}'")


@app.post("/servers/{name}/plug")
async def plug(name: str):
    _known(name)
    registry.plug(name)
    return await servers()


@app.post("/servers/{name}/unplug")
async def unplug(name: str):
    _known(name)
    registry.unplug(name)
    return await servers()


def _key(name, args):
    return f"{name} {json.dumps(args, sort_keys=True)}"


def _remember(out):
    """What a session keeps of an answer: the conclusion, never the raw tool results."""
    return {"verdict": out["verdict"]["verdict"], "headline": out["verdict"]["headline"], "intent": out["intent"]}


@app.post("/ask")
async def ask(body: Question):
    session = body.session_id or store.new_session()
    out = await run_question(body.question, store.history(session))
    store.add_turn(session, body.question, _remember(out))
    return out | {"session_id": session}


@app.post("/agent")
async def agent_goal(body: Goal):
    """Server-sent events: session, tool (one per call, with Guardian's decision), message, done."""
    session = body.session_id or store.new_session()

    async def events():
        yield _sse({"type": "session", "id": session})
        final = None
        async for ev in _agent_events(body.goal, store.history(session), session):
            final = ev["text"] if ev["type"] == "message" else final
            yield _sse(ev)
        store.add_turn(session, body.goal, {"headline": final})
        yield _sse({"type": "done"})

    return StreamingResponse(events(), media_type="text/event-stream")


def _sse(event):
    return f"data: {json.dumps(event)}\n\n"


def _public(action):
    return {k: v for k, v in action.items() if k not in ("session", "hold_id")}


def _proposals(answer):
    """The exact options the engine priced (fares, hotel, top offer), as holds. The rules path's way to prepare a plan."""
    v, intent = answer["verdict"], answer["intent"]
    out = []
    for part in v["numbers"].get("breakdown") or []:
        if part["key"] == "flight":
            out += [("booking__hold_flight", {"origin": leg["from"], "dest": leg["to"], "date": leg["date"],
                                              "airline": leg["airline"], "depart": leg["depart"], "price": leg["price"]})
                    for leg in part.get("legs") or []]
        elif part["key"] == "stay" and part.get("hotel"):
            out.append(("booking__hold_stay", {"city": intent["city"], "check_in": intent["start"], "check_out": intent["end"],
                                               "hotel": part["hotel"]["name"], "per_night": part["hotel"]["per_night"]}))
        elif part["key"] == "product" and part.get("offers"):
            o = part["offers"][0]
            out.append(("booking__hold_order", {"item": o["title"], "store": o["store"], "price": o["price"],
                                                "link": o.get("link") or ""}))
    return out


BOOK = re.compile(r"\b(book|hold|reserve|order|buy it|get it)\b", re.I)


async def _agent_events(goal, history, session=None):
    tools = (await registry.discover())["tools"] + [agent.PLAN_TOOL]
    guard = guardian.Guard(tools, goal)
    trace, approvals = [], []

    def flush():  # each hold the agent made becomes a card you approve or decline
        while approvals:
            yield {"type": "approval", "action": _public(approvals.pop(0))}

    async def call(name, args):
        if name == agent.PLAN_TOOL["name"]:  # Orbit's own pipeline, in process: same engine, own Guardian per question
            start = time.perf_counter()
            r = {"server": "orbit", "tool": "check_plan", "args": args, "ts": agent._now()}
            try:
                out = await run_question(args.get("question", ""), history, explain=False)
                r.update(ok=True, result={"verdict": out["verdict"], "intent": out["intent"]}, answer=out)
            except Exception as e:
                r.update(ok=False, error=f"{type(e).__name__}: {e}"[:200])
            r["ms"] = round((time.perf_counter() - start) * 1000)
        else:
            r = await registry.call(name, args)
            if r["ok"] and name.startswith("booking__hold_"):
                approvals.append(store.add_action(session, r["result"]))
        guard.saw(r)
        return r

    async def hold(answer):
        """"Book it", done by the rules: hold the exact options the engine priced, each one checked by Guardian.
        Returns (events, a sentence for the reply)."""
        events, held = [], 0
        for name, args in _proposals(answer):
            decision, why = guard.check(name, args)
            h = await call(name, args) if decision == "allowed" else {
                "server": "booking", "tool": name.partition("__")[2], "args": args, "ok": False, "ms": 0, "error": why}
            row = agent.entry(h, "rules", decision)
            trace.append(row)
            events += [{"type": "tool", **row}, *flush()]
            held += h["ok"]
        if held:
            return events, f" I've put {held} option{'s' if held != 1 else ''} on hold for you to approve."
        return events, " Nothing was put on hold: Orbit only holds a plan its engine says fits your money."

    started, reply, error = False, None, None
    if GEMINI:
        try:
            async for ev in agent.run(goal, history, tools, call, guard.check, GEMINI, agent.models()):
                started = True
                if ev["type"] == "message":  # held back: a "book it" the model didn't finish is finished below
                    reply = ev
                    continue
                trace += [ev] if ev["type"] == "tool" else []
                yield ev
                for card in flush():
                    yield card
        except Exception as e:
            error = str(e)[:120]
            if not started:
                yield {"type": "step", "text": f"Model unavailable ({error}): checking it as one plan."}
    if started:
        answers = [t["answer"] for t in trace if t.get("answer")]
        # A plan already checked stands on its own if the model stopped partway; otherwise say why we stopped.
        reply = reply or {"type": "message", "model": None, "text": answers[-1]["verdict"]["headline"] if answers else
                          f"The model stopped answering partway through ({error}). Try again."}
        tried = any(t.get("server") == "booking" for t in trace)
        if answers and BOOK.search(goal) and not tried:  # asked to book, the model never got to it: the rules do
            events, note = await hold(answers[-1])
            for ev in events:
                yield ev
            reply["text"] += note
        yield reply
    else:  # no model: the goal is checked as a single plan by the rules planner
        decision, why = guard.check(agent.PLAN_TOOL["name"], {"question": goal})
        if decision != "allowed":
            yield {"type": "message", "text": f"Blocked by Orbit Guardian: {why}", "model": None}
        else:
            r = await call(agent.PLAN_TOOL["name"], {"question": goal})
            row = agent.entry(r, "rules") | ({"answer": r["answer"]} if r["ok"] else {})
            trace.append(row)
            yield {"type": "tool", **row}
            text = r["result"]["verdict"]["headline"] if r["ok"] else r["error"]
            if r["ok"] and BOOK.search(goal):
                events, note = await hold(r["answer"])
                for ev in events:
                    yield ev
                text += note
            yield {"type": "message", "text": text, "model": None}
    for card in flush():
        yield card
    guardian.audit(goal, trace)


MAX_APPROVAL = int(os.getenv("ORBIT_MAX_APPROVAL") or 50_000)  # per action, in rupees; bigger ones you do yourself
HEX32 = r"^[0-9a-f]{32}$"


class Approval(BaseModel):
    hash: str = Field(pattern=HEX32)  # the version of the hold you saw


def _action_or_404(action_id):
    a = store.get_action(action_id) if re.fullmatch(HEX32, action_id) else None
    if not a:
        raise HTTPException(404, "No such action")
    return a


@app.get("/actions")
def list_actions():
    """Every booking the agent prepared, newest first (the Bookings window). Holds past their expiry say so."""
    now = datetime.now(timezone.utc)
    for a in store.all_actions():
        if a["status"] == "pending" and datetime.fromisoformat(a["expires_at"]) <= now:
            store.move(a["id"], "pending", "expired")
    return {"actions": [_public(a) for a in store.all_actions()]}


@app.post("/actions/{action_id}/approve")
async def approve(action_id: str, body: Approval):
    """You approving on screen IS the authorization (like uploading a statement): the model has no way to reach this."""
    a = _action_or_404(action_id)
    if not hmac.compare_digest(a["hash"].encode(), body.hash.encode()):
        raise HTTPException(409, "This hold changed since you saw it. Look at it again before approving.")
    # ponytail: the cap is in rupees, so it skips other currencies; only Duffel TEST fares (GBP/USD) use them today.
    if a["currency"] == "INR" and a["amount"] > MAX_APPROVAL:
        raise HTTPException(403, f"Over your approval limit of Rs {MAX_APPROVAL:,}. Book this one yourself.")
    if not store.move(action_id, "pending", "approving"):
        raise HTTPException(409, f"This hold is already {a['status']}")
    r = await registry.call("booking__confirm_hold", {"hold_id": a["hold_id"]})
    row = {"server": "booking", "tool": "confirm_hold", "args": {"hold_id": a["hold_id"]}, "by": "you",
           "guardian": "approved by you", "error": None if r["ok"] else r["error"][:200]}
    guardian.audit(f"approve: {a['summary']}", [row])
    if not r["ok"]:
        store.move(action_id, "approving", "expired" if "expired" in r["error"] else "failed", {"error": r["error"][:200]})
        raise HTTPException(409, f"Couldn't confirm it: {r['error'][-120:]}")
    store.move(action_id, "approving", "confirmed", {k: r["result"].get(k) for k in ("reference", "payment", "confirmed_at")})
    return _public(store.get_action(action_id))


@app.post("/actions/{action_id}/decline")
async def decline(action_id: str):
    a = _action_or_404(action_id)
    if not store.move(action_id, "pending", "declined"):
        raise HTTPException(409, f"This hold is already {a['status']}")
    await registry.call("booking__release_hold", {"hold_id": a["hold_id"]})  # best effort: holds expire anyway
    guardian.audit(f"decline: {a['summary']}", [{"server": "booking", "tool": "release_hold", "args": {"hold_id": a["hold_id"]},
                                                 "by": "you", "guardian": "declined by you", "error": None}])
    return _public(store.get_action(action_id))


async def run_question(question, history=(), explain=True):
    """One question through the whole pipeline: understand, read (Guardian on every call), engine, explain."""
    catalogue = await registry.discover()
    tools = catalogue["tools"]

    guard = guardian.Guard(tools, question)
    check = guard.check

    async def call(name, args):
        r = await registry.call(name, args)
        guard.saw(r)  # private values read here can't leave in a later outbound call
        return r

    # 1. Understand: Gemini turns the question into an intent; code validates it. Rules parser if no model answers.
    chain, model, intent, planner_used = agent.models(), None, None, "rules"
    if GEMINI:
        try:
            model, raw = await agent.understand(question, TODAY, GEMINI, chain, history)
            chain, intent, planner_used = [model], planner.validate(raw, TODAY), "gemini"
        except Exception as e:
            planner_used = f"rules (Gemini unavailable: {str(e)[:120]})"
    intent = intent or planner.parse(question, TODAY)
    other = intent["kind"] == "other"
    # Not a plan: read nothing unless the model picks a tool for it ("what's on my calendar?"). Small talk reads no data.
    canonical = [] if other else planner.plan(intent, tools, TODAY)
    needed = {_key(n, a) for n, a in canonical}

    def enough(executed):
        return not other and needed <= {_key(f"{r['server']}__{r['tool']}", r["args"]) for r in executed if r["ok"]}

    # 2. Gather: the model chooses what to read; Guardian checks every call it asks for.
    executed, trace, answer = [], [], None
    if model and tools:  # no point asking a model to plan with zero tools
        try:
            _, executed, trace, answer = await agent.gather(
                question, planner.facts(intent, TODAY), tools, call, check, GEMINI, chain, enough,
                system=agent.ANSWER if other else agent.SYSTEM)
        except Exception as e:
            planner_used = f"rules (Gemini unavailable: {str(e)[:120]})"

    # The numbers only use the canonical reads; whatever the model skipped or asked for differently is filled in here.
    done = {_key(f"{r['server']}__{r['tool']}", r["args"]): r for r in executed if r["ok"]}
    missing = [(n, a) for n, a in canonical if _key(n, a) not in done and check(n, a)[0] == "allowed"]
    topped_up = await asyncio.gather(*(call(n, a) for n, a in missing))
    trace += [agent.entry(r, "rules") for r in topped_up]
    done |= {_key(n, a): r for (n, a), r in zip(missing, topped_up)}
    results = [done[_key(n, a)] for n, a in canonical if _key(n, a) in done]
    # Plugged-in servers that didn't answer show up in the receipt as FAILED, not silently as "not read".
    results += [{"server": n, "tool": "tools/list", "args": {}, "ok": False, "ms": 0, "error": f"server offline ({why})"}
                for n, why in catalogue["offline"].items()]

    # 3. Decide (deterministic engine), 4. explain (model, words only).
    verdict = engine.decide(question, intent, results, [s for s in SERVERS if s != "booking"])  # sources, not actions
    explanation = None
    if other:
        verdict["headline"] = answer or ("I can't help with that one. I can plan your weekend, check if a trip or a "
                                         "purchase fits your budget, and hold bookings for your OK. "
                                         'Try: "Book a Goa trip next weekend".')
    elif model and explain:
        try:
            explanation = await agent.explain(verdict, GEMINI, model)
        except Exception:
            pass  # the verdict stands on its own; the explanation is a nice-to-have
    guardian.audit(question, trace)
    shown = {k: v.isoformat() if isinstance(v, date) else v for k, v in intent.items()}
    return {"verdict": verdict, "explanation": explanation, "trace": trace, "planner": planner_used,
            "model": model, "intent": shown, "offline": catalogue["offline"]}


if __name__ == "__main__":
    import uvicorn

    here = str(Path(__file__).resolve().parent)
    # reload=True: editing any backend file restarts the API, so a stale backend can't serve old code
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True, app_dir=here, reload_dirs=[here])
