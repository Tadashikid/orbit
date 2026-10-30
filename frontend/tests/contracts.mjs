// Adapter contract: src/api.ts against real backend responses (tests/fixtures/backend.json via fake-backend.mjs).
import assert from "node:assert/strict";
import { createServer } from "vite";
import { DEMO_EMAIL, DEMO_PASSWORD, fakeBackend, fixtures, HERO } from "./fake-backend.mjs";
const server = await createServer({
  root: process.cwd(),
  server: { middlewareMode: true },
  appType: "custom",
  optimizeDeps: { noDiscovery: true, include: [] },
});
try {
  const { api, toResult, ApiError } = await server.ssrLoadModule("/src/api.ts");
  // The demo login: signed out, a wrong password is refused, then /me knows who signed in, until logout.
  const signedOut = fakeBackend({ signedIn: false });
  globalThis.fetch = signedOut.fetch;
  assert.equal(await api.me(), null);
  await assert.rejects(api.login(DEMO_EMAIL, "wrong"), /Wrong email or password/);
  assert.equal(await api.login(DEMO_EMAIL, DEMO_PASSWORD), DEMO_EMAIL);
  assert.equal(await api.me(), DEMO_EMAIL);
  await api.logout();
  assert.equal(await api.me(), null);
  const fake = fakeBackend();
  globalThis.fetch = fake.fetch;
  // The registry: backend names mapped to the UI's, real status and tools; Finance starts off.
  const { servers, today } = await api.servers();
  assert.equal(today, "2026-10-08");
  assert.deepEqual(
    servers.map((s) => [s.id, s.name, s.status, s.permission]),
    [
      ["calendar", "Calendar", "connected", "allow"],
      ["tasks", "Tasks", "connected", "allow"],
      ["finance", "Finance", "off", "off"],
      ["travel", "Travel", "connected", "allow"],
      ["price", "Price Check", "connected", "allow"],
      ["booking", "Bookings", "connected", "allow"], // holds only; switching it off means nothing can be held
    ],
  );
  assert.deepEqual(servers.find((s) => s.id === "travel").tools.map((t) => t.name), ["search_flights", "search_hotels"]);
  // Before Finance: the engine's answer passes through; every evidence row resolves to a registered server.
  const before = await api.decide(HERO, servers);
  assert.equal(before.wire.verdict, "yes");
  assert.equal(before.wire.numbers.balance, null);
  assert.deepEqual(before.wire.numbers.trip_cost, fixtures.ask_without_finance[HERO].verdict.numbers.trip_cost);
  assert(before.wire.not_read.includes("Finance: switched off"));
  assert(before.wire.evidence.every((e) => servers.some((s) => s.name === e.server)));
  assert.equal(before.confidence, "low"); // seeded sample fares: the UI-only freshness label says so
  assert(before.trace.length > 0);
  for (const t of before.trace) {
    assert.match(t.tool, /^tools\/call \w+ · rules planner$/);
    assert(t.ts.startsWith("2026-"), "a real backend timestamp, not a made-up one");
    assert.equal(t.status, "ok");
  }
  assert.equal(await api.statement(), null);
  // Finance on: its write tool is announced as a write; the statement is masked by the backend.
  const { servers: on } = await api.setSource("finance", true);
  assert.deepEqual(
    on.find((s) => s.id === "finance").tools.filter((t) => t.kind === "write").map((t) => t.name),
    ["load_statement"],
  );
  assert.deepEqual(await api.samples(), fixtures["GET /statement/samples"].samples);
  const st = await api.uploadStatement({ sample: "manu_statement" });
  assert.equal(st.balance, 54263);
  assert.deepEqual(st.receipt.dropped_columns, ["Narration", "Mode"]);
  assert.equal((await api.statement()).balance, 54263);
  // After Finance: the engine's numbers, untouched; the breakdown and the math add up to them.
  const after = await api.decide(HERO, on);
  const n = after.wire.numbers;
  assert.equal(after.wire.verdict, "yes_with_conditions");
  assert.deepEqual(n.trip_cost, fixtures.ask_with_finance[HERO].verdict.numbers.trip_cost);
  assert.deepEqual(n.breakdown.map((p) => p.key), ["flight", "stay", "other"]);
  assert.equal(n.breakdown.reduce((a, p) => a + p.low, 0), n.trip_cost.low);
  assert.equal(n.math.at(-1).amount, n.remaining.low);
  assert(after.wire.evidence.some((e) => e.source === "statement"));
  assert(after.wire.evidence.some((e) => e.source === "estimate"));
  assert.equal(after.explanation, null); // the rules planner answered: no model wording to show
  const table = await api.decide("Can I buy a table?", on);
  assert.equal(table.wire.numbers.breakdown[0].key, "product");
  assert.equal((await api.decide("Should I learn guitar?", on)).wire.verdict, "info");
  // The agent: the conversation id goes back with the next question; a reply that checked several plans shows the
  // last one in the agent's words, with live steps; a reply that checked no plan is still an answer card.
  const sent = [];
  const steps = [];
  const plan = (q, answer) => ({ type: "tool", server: "orbit", tool: "check_plan", args: { question: q }, ok: true,
    ms: 1, by: "gemini", guardian: "allowed", ts: "2026-10-08T10:00:00.000+05:30", answer });
  globalThis.fetch = async (url, init) => {
    sent.push(JSON.parse(init.body));
    const events = sent.length === 1
      ? [{ type: "session", id: "a".repeat(32) },
         plan("Goa?", fixtures.ask_with_finance[HERO]), plan("Table?", fixtures.ask_with_finance["Can I buy a table?"]),
         { type: "tool", server: "finance", tool: "load_statement", ok: false, ms: 0, by: "gemini", guardian: "needs_approval",
           ts: "2026-10-08T10:00:01.000+05:30" },
         { type: "message", text: "Goa fits, and the table is easy too." }, { type: "done" }]
      : [{ type: "session", id: "a".repeat(32) }, { type: "message", text: "You have 2 deadlines this week." }, { type: "done" }];
    return new Response(events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join(""));
  };
  api.newConversation();
  const both = await api.decide("Goa or a table?", on, (s) => steps.push(s));
  assert.equal(sent[0].session_id, undefined); // a new conversation
  assert.equal(both.wire.numbers.breakdown[0].key, "product"); // the last plan checked
  assert.equal(both.explanation, "Goa fits, and the table is easy too.");
  assert.deepEqual(steps, ["Checked: Goa?", "Checked: Table?", "Guardian stopped load_statement"]);
  assert(both.trace.some((t) => t.status === "denied"));
  const chat = await api.decide("Any deadlines?", on);
  assert.equal(sent[1].session_id, "a".repeat(32)); // same conversation
  assert.deepEqual([chat.wire.verdict, chat.wire.headline], ["info", "You have 2 deadlines this week."]);
  // Holds: an approval card comes with the plan; approving sends back the version of the hold you saw.
  const card = { id: "b".repeat(32), kind: "flight", summary: "IndiGo BLR→GOI Sat 10 Oct 21:00", amount: 6411,
    expires_at: "2026-10-08T10:30:00+05:30", hash: "c".repeat(32), status: "pending" };
  const posted = [];
  globalThis.fetch = async (url, init) => {
    posted.push([String(url), JSON.parse(init.body)]);
    if (String(url).endsWith("/agent"))
      return new Response([{ type: "session", id: "a".repeat(32) }, plan("Book Goa", fixtures.ask_with_finance[HERO]),
        { type: "approval", action: card }, { type: "message", text: "Held 1 option." }, { type: "done" }]
        .map((e) => `data: ${JSON.stringify(e)}\n\n`).join(""));
    return new Response(JSON.stringify({ ...card, status: "confirmed", outcome: { reference: "ORB-ABC123" } }));
  };
  const booked = await api.decide("Book Goa", on, (s) => steps.push(s));
  assert.deepEqual(booked.approvals, [card]);
  assert.equal(steps.at(-1), `Held: ${card.summary}`);
  assert.equal((await api.approve(card)).status, "confirmed");
  assert.deepEqual(posted.at(-1), [`/api/actions/${card.id}/approve`, { hash: card.hash }]);
  globalThis.fetch = async (url) => new Response(JSON.stringify({ actions: [card] }), { status: String(url) === "/api/actions" ? 200 : 404 });
  assert.deepEqual(await api.actions(), [card]); // the Bookings window's list
  // Never shows a malformed answer, never pretends when the backend is down.
  assert.throws(() => toResult({ verdict: { verdict: "maybe" } }, on), ApiError);
  globalThis.fetch = async () => {
    throw new TypeError("Failed to fetch");
  };
  await assert.rejects(api.servers(), /Can't reach Orbit/);
  console.log(
    "PASS: adapter contract — registry mapping, engine numbers passed through, real trace timestamps, statement upload, breakdown/math consistency, malformed and offline answers rejected.",
  );
} finally {
  await server.close();
}
