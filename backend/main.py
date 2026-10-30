"""Orbit API on 127.0.0.1:8000. Needs the MCP servers running (run_servers.py).

    .venv\\Scripts\\python backend\\main.py

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
import json
import os
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
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
registry = Registry(plugged=("calendar", "gmail", "travel", "price"))  # ponytail: one shared registry = one user (demo)


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
        async for ev in _agent_events(body.goal, store.history(session)):
            final = ev["text"] if ev["type"] == "message" else final
            yield _sse(ev)
        store.add_turn(session, body.goal, {"headline": final})
        yield _sse({"type": "done"})

    return StreamingResponse(events(), media_type="text/event-stream")


def _sse(event):
    return f"data: {json.dumps(event)}\n\n"


async def _agent_events(goal, history):
    tools = (await registry.discover())["tools"] + [agent.PLAN_TOOL]
    guard = guardian.Guard(tools, goal)
    trace = []

    async def call(name, args):
        if name == agent.PLAN_TOOL["name"]:  # Orbit's own pipeline, in process: same engine, own Guardian per question
            start = time.perf_counter()
            r = {"server": "orbit", "tool": "check_plan", "args": args, "ts": agent._now()}
            try:
                out = await run_question(args.get("question", ""), history, explain=False)
                r.update(ok=True, result={"verdict": out["verdict"], "intent": out["intent"]})
            except Exception as e:
                r.update(ok=False, error=f"{type(e).__name__}: {e}"[:200])
            r["ms"] = round((time.perf_counter() - start) * 1000)
        else:
            r = await registry.call(name, args)
        guard.saw(r)
        return r

    started = False
    if GEMINI:
        try:
            async for ev in agent.run(goal, history, tools, call, guard.check, GEMINI, agent.models()):
                started = True
                trace += [ev] if ev["type"] == "tool" else []
                yield ev
        except Exception as e:
            if started:
                yield {"type": "message", "text": "The model stopped answering partway through. Try again.", "model": None}
            else:
                yield {"type": "step", "text": f"Model unavailable ({str(e)[:120]}): checking it as one plan."}
    if not started:  # no model: the goal is checked as a single plan by the rules planner
        decision, why = guard.check(agent.PLAN_TOOL["name"], {"question": goal})
        if decision != "allowed":
            yield {"type": "message", "text": f"Blocked by Orbit Guardian: {why}", "model": None}
        else:
            r = await call(agent.PLAN_TOOL["name"], {"question": goal})
            row = agent.entry(r, "rules") | ({"result": r["result"]} if r["ok"] else {})
            trace.append(row)
            yield {"type": "tool", **row}
            yield {"type": "message", "text": r["result"]["verdict"]["headline"] if r["ok"] else r["error"], "model": None}
    guardian.audit(goal, trace)


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
    canonical = planner.plan(intent, tools, TODAY)
    needed = {_key(n, a) for n, a in canonical}
    other = intent["kind"] == "other"

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
    verdict = engine.decide(question, intent, results, list(SERVERS))
    explanation = None
    if other:
        verdict["headline"] = answer or ('I can answer trips, purchases, outings and savings goals. '
                                         'Try: "Can I buy a laptop this month?"')
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
