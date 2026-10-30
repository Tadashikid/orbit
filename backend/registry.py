"""MCP registry: which servers are plugged in, what tools they offer, and routing calls to them.

Nothing here knows what a server *does*. Tools are discovered at runtime with tools/list and named
"<server>__<tool>", so the catalogue can go straight to Gemini as function declarations, and every
call is routed back to its owning server with tools/call. Plug a server in and the next discover()
sees its tools. That is the whole hot-plug.

Try it (servers must be running first:  .venv\\Scripts\\python run_servers.py):
    .venv\\Scripts\\python backend\\registry.py
"""
import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

# Where each MCP server lives. This is config (like an MCP client config file), not decision logic.
# 127.0.0.1, not "localhost": on Windows, localhost tries IPv6 first and costs ~1.3 s per call (measured).
# ORBIT_PORT_OFFSET: the tests run their own servers on other ports, so they never touch your running ones.
_OFFSET = int(os.getenv("ORBIT_PORT_OFFSET", "0"))
SERVERS = {name: f"http://127.0.0.1:{port + _OFFSET}/mcp"
           for name, port in (("calendar", 8101), ("gmail", 8102), ("finance", 8103), ("travel", 8104), ("price", 8105), ("booking", 8106))}
TIMEOUT_S = 10  # a cold live Gmail fetch takes ~3 s
SLOW_S = {"booking": 45}  # a Duffel hold is two calls (search fares, create the order): often more than 10 s
IST = timezone(timedelta(hours=5, minutes=30))


@asynccontextmanager
async def _session(url):
    async with streamable_http_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _why(e):
    while isinstance(e, BaseExceptionGroup) and e.exceptions:  # anyio wraps connection errors
        e = e.exceptions[0]
    return f"{type(e).__name__}: {e}"[:200] if str(e) else type(e).__name__


class Registry:
    def __init__(self, plugged=("calendar", "gmail")):
        self.plugged = {name: SERVERS[name] for name in plugged}

    def plug(self, name, url=None):
        self.plugged[name] = url or SERVERS[name]

    def unplug(self, name):
        self.plugged.pop(name, None)

    async def _list(self, name, url):
        async with asyncio.timeout(TIMEOUT_S), _session(url) as s:
            tools = (await s.list_tools()).tools
        return [
            {
                "name": f"{name}__{t.name}",
                "server": name,
                "tool": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema,
                "read_only": bool(t.annotations and t.annotations.readOnlyHint),  # Guardian gates the rest
                "destructive": bool(t.annotations and t.annotations.destructiveHint),
            }
            for t in tools
        ]

    async def discover(self):
        """{"tools": [...], "offline": {server: reason}}. One tools/list per plugged server, in parallel."""
        names = list(self.plugged)
        results = await asyncio.gather(*(self._list(n, self.plugged[n]) for n in names), return_exceptions=True)
        tools, offline = [], {}
        for name, r in zip(names, results):
            if isinstance(r, BaseException):
                offline[name] = _why(r)
            else:
                tools += r
        return {"tools": tools, "offline": offline}

    async def call(self, qualified_name, args=None, meta=None):
        """Route "<server>__<tool>" to its server. Never raises: failures come back with ok=False.
        `meta` rides in the request's _meta (the user's Google token), never in `args`, so it isn't in the result."""
        server, _, tool = qualified_name.partition("__")
        out = {"server": server, "tool": tool, "args": args or {}, "ts": datetime.now(IST).isoformat(timespec="milliseconds")}
        if server not in self.plugged:
            return {**out, "ok": False, "error": f"server '{server}' is not plugged in", "ms": 0}
        start = time.perf_counter()
        try:
            async with asyncio.timeout(SLOW_S.get(server, TIMEOUT_S)), _session(self.plugged[server]) as s:
                res = await s.call_tool(tool, args or {}, meta=meta)
            text = res.content[0].text if res.content else ""
            out.update(ok=False, error=text) if res.isError else out.update(ok=True, result=json.loads(text))
        except Exception as e:
            out.update(ok=False, error=_why(e))
        return {**out, "ms": round((time.perf_counter() - start) * 1000)}


async def _demo():
    reg = Registry()
    first = await reg.discover()
    if first["offline"]:
        print("OFFLINE:", first["offline"], "\n-> start the servers first:  .venv\\Scripts\\python run_servers.py")
        return
    print(f"plugged {list(reg.plugged)} -> {len(first['tools'])} tools: {[t['name'] for t in first['tools']]}")

    r = await reg.call("gmail__get_deadlines", {"start": "2026-10-10", "end": "2026-10-12"})
    print(f"gmail__get_deadlines   ok={r['ok']} {r['ms']} ms source={r.get('result', {}).get('source')}")
    r = await reg.call("finance__get_balance")
    print(f"finance__get_balance   ok={r['ok']} ({r.get('error')})")

    reg.plug("finance")
    second = await reg.discover()
    new = sorted({t["name"] for t in second["tools"]} - {t["name"] for t in first["tools"]})
    print(f"\nplugged finance -> {len(second['tools'])} tools, new: {new}")
    print("write tools (need approval):", [t["name"] for t in second["tools"] if not t["read_only"]])
    r = await reg.call("finance__get_balance")
    print(f"finance__get_balance   ok={r['ok']} {r['ms']} ms balance={r.get('result', {}).get('balance')}")


if __name__ == "__main__":
    asyncio.run(_demo())
