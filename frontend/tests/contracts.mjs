// Adapter contract: src/api.ts against real backend responses (tests/fixtures/backend.json via fake-backend.mjs).
import assert from "node:assert/strict";
import { createServer } from "vite";
import { fakeBackend, fixtures, HERO } from "./fake-backend.mjs";
const server = await createServer({
  root: process.cwd(),
  server: { middlewareMode: true },
  appType: "custom",
  optimizeDeps: { noDiscovery: true, include: [] },
});
try {
  const { api, toResult, ApiError } = await server.ssrLoadModule("/src/api.ts");
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
