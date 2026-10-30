// A stand-in for the Orbit API in the UI tests. It replays real responses captured from backend/main.py
// (tests/fixtures/backend.json, made by scripts/capture_ui_fixtures.py) and keeps the little state the API keeps:
// which servers are plugged in and whether a statement is loaded. Like the real registry, an unplugged server
// is never read: its evidence and trace rows are left out of the answer.
import { readFileSync } from "node:fs";
export const fixtures = JSON.parse(
  readFileSync(new URL("./fixtures/backend.json", import.meta.url), "utf8"),
);
export const HERO = "Can I afford a Goa trip next weekend?";
export function fakeBackend({ finance = false, statement = false } = {}) {
  const listed = fixtures["GET /servers"];
  const financeTools = fixtures["POST /servers/finance/plug"].servers.find((s) => s.name === "finance").tools;
  const state = {
    plugged: new Set(listed.servers.filter((s) => s.plugged).map((s) => s.name)),
    statement,
  };
  if (finance) state.plugged.add("finance");
  const calls = [];
  const servers = () => ({
    today: listed.today,
    servers: listed.servers.map((s) => {
      const on = state.plugged.has(s.name);
      const tools = s.name === "finance" ? financeTools : s.tools;
      return { ...s, plugged: on, status: on ? "connected" : "off", tools: on ? tools : [] };
    }),
  });
  const json = (body, status = 200) => ({ ok: status < 400, status, text: async () => JSON.stringify(body) });
  const answer = (question) => {
    const set = state.plugged.has("finance") && state.statement ? fixtures.ask_with_finance : fixtures.ask_without_finance;
    if (!set[question]) return json({ detail: `no fixture for "${question}"` }, 500);
    const r = structuredClone(set[question]);
    const read = (server) => state.plugged.has(server);
    r.verdict.evidence = r.verdict.evidence.filter((e) => read(e.server));
    r.verdict.not_read = [...new Set([...r.verdict.not_read, ...listed.servers.map((s) => s.name).filter((n) => !read(n))])];
    r.trace = r.trace.filter((t) => read(t.server));
    return json(r);
  };
  const fetch = async (url, init = {}) => {
    const method = init.method || "GET";
    const path = String(url).replace(/^\/api/, "");
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push(`${method} ${path}`);
    let m;
    if (method === "GET" && path === "/servers") return json(servers());
    if (method === "POST" && (m = /^\/servers\/(\w+)\/(plug|unplug)$/.exec(path))) {
      if (m[2] === "plug") state.plugged.add(m[1]);
      else state.plugged.delete(m[1]);
      return json(servers());
    }
    if (method === "GET" && path === "/statement/samples") return json(fixtures["GET /statement/samples"]);
    if (method === "GET" && path === "/statement")
      return json(state.plugged.has("finance") && state.statement ? fixtures["GET /statement"] : null);
    if (method === "POST" && path === "/statement") {
      if (!state.plugged.has("finance")) return json({ detail: "Plug in Finance first" }, 409);
      state.statement = true;
      return json(fixtures["POST /statement"]);
    }
    if (method === "POST" && path === "/ask") return answer(body.question);
    return json({ detail: "Not Found" }, 404);
  };
  return { fetch, calls, state };
}
