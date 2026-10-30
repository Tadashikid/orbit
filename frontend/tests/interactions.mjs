import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { createServer } from "vite";
import React from "react";
import { readFileSync } from "node:fs";
const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  url: "http://localhost",
  pretendToBeVisual: true,
});
for (const name of [
  "window",
  "document",
  "HTMLElement",
  "Element",
  "Node",
  "MutationObserver",
  "getComputedStyle",
  "sessionStorage",
  "localStorage",
  "Event",
  "EventTarget",
  "MouseEvent",
  "KeyboardEvent",
  "SVGElement",
])
  globalThis[name] = dom.window[name];
Object.defineProperty(globalThis, "navigator", {
  value: dom.window.navigator,
  configurable: true,
});
window.matchMedia = (q) => ({
  matches: q.includes("prefers-reduced-motion"),
  media: q,
  addListener() {},
  removeListener() {},
  addEventListener() {},
  removeEventListener() {},
  dispatchEvent() {
    return true;
  },
});
globalThis.requestAnimationFrame = window.requestAnimationFrame.bind(window);
globalThis.cancelAnimationFrame = window.cancelAnimationFrame.bind(window);
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
window.ResizeObserver = globalThis.ResizeObserver;
globalThis.IntersectionObserver = class {
  constructor(callback) {
    this.callback = callback;
  }
  observe(target) {
    this.callback([{ target, isIntersecting: true, intersectionRatio: 1 }]);
  }
  unobserve() {}
  disconnect() {}
};
window.IntersectionObserver = globalThis.IntersectionObserver;
HTMLElement.prototype.scrollIntoView = function () {};
const { render, fireEvent, screen, waitFor, cleanup } =
  await import("@testing-library/react");
const vite = await createServer({
  root: process.cwd(),
  server: { middlewareMode: true },
  appType: "custom",
  optimizeDeps: { noDiscovery: true, include: [] },
});
const errors = [];
const old = console.error;
console.error = (...args) => {
  errors.push(args.join(" "));
  old(...args);
};
// The real UI against real backend responses (tests/fixtures/backend.json), replayed by fake-backend.mjs.
const { fakeBackend, fixtures, HERO } = await import("./fake-backend.mjs");
const fake = fakeBackend();
globalThis.fetch = fake.fetch;
window.fetch = fake.fetch;
try {
  const { default: App } = await vite.ssrLoadModule("/src/App.tsx");
  render(React.createElement(App));
  // The registry is hydrated from GET /servers: the dock lists the backend's servers.
  await waitFor(() => assert(document.querySelector('.dock-icon[data-source-id="travel"]')));
  assert(!screen.queryByRole("dialog"));
  assert(screen.getByRole("heading", { name: /BIG PLANS.CLEAR ANSWERS/ }));
  assert(!screen.queryByText("mcp_trace.log"));
  assert(screen.getByRole("button", { name: "Your balance" }).textContent.includes("Add balance"));
  // Before Finance: the trip's three cards, priced from the engine's breakdown.
  fireEvent.click(screen.getByRole("button", { name: "A Goa weekend", exact: true }));
  await waitFor(() => assert(screen.getByRole("button", { name: /Your plan is ready/ })), { timeout: 5000 });
  assert.deepEqual(
    [...document.querySelectorAll(".journey-card h3")].map((e) => e.textContent),
    ["FIRST, GETTING THERE.", "THEN, A PLACE TO UNWIND.", "AND THE LITTLE THINGS."],
  );
  assert(screen.getByRole("heading", { name: "A WEEKEND IN GOA." }));
  assert.equal(document.querySelector(".journey-stay .tab-budget-label").textContent, "SAMPLE PRICES");
  assert.equal(document.querySelector(".journey-other .card-budget strong").textContent, "Not priced yet");
  assert(screen.getByRole("heading", { name: "ALL TOGETHER NOW." }));
  // The engine flagged the injected email; the notice says so (nothing is simulated).
  assert(screen.getByText("We ignored an unsafe instruction in your email. Nothing was changed."));
  // Add your budget: the real hot-plug and the tools Finance announces.
  fireEvent.click(screen.getByRole("button", { name: "Add your budget", exact: true }));
  fireEvent.click(screen.getByRole("button", { name: "Connect budget", exact: true }));
  await waitFor(() => assert(screen.getByText("load_statement")));
  assert(fake.calls.includes("POST /servers/finance/plug"));
  fireEvent.click(screen.getByRole("button", { name: "Done", exact: true }));
  // Add a statement: the demo statement goes through the real masked upload; the balance is read-only.
  fireEvent.click(screen.getByRole("button", { name: "Add a statement" }));
  const csv = readFileSync(new URL("../../data/samples/manu_statement.csv", import.meta.url), "utf8");
  fireEvent.change(document.querySelector('input[type="file"]'), { target: { files: [new File([csv], "statement.csv", { type: "text/csv" })] } });
  await waitFor(() => assert(screen.getByText("STATEMENT READY")), { timeout: 2000 });
  assert(screen.getByText(/Left out Narration, Mode/));
  fireEvent.click(screen.getByRole("button", { name: "Continue", exact: true }));
  assert(screen.getByLabelText("Balance from your statement").textContent.includes("54,263"));
  assert(!screen.queryByRole("spinbutton")); // nothing to type: the balance comes from the statement
  fireEvent.click(screen.getByRole("button", { name: "Done", exact: true }));
  await waitFor(() => assert(!screen.queryByRole("dialog")));
  // Ask again with Finance: the engine's verdict and plan.
  fireEvent.click(screen.getByRole("button", { name: "Check my plan again" }));
  const after = fixtures.ask_with_finance[HERO].verdict;
  await waitFor(() => assert(screen.getByRole("heading", { name: after.headline })), { timeout: 5000 });
  assert(!document.querySelector(".summary-options")); // the plan lives in the insights, not the summary
  // Technical evidence appears only on demand, from real records.
  fireEvent.click(screen.getByRole("button", { name: /View detailed insights/ }));
  assert(screen.getByRole("dialog", { name: "THE DETAILS BEHIND YOUR PLAN." }));
  await waitFor(() => assert(screen.getByRole("button", { name: "TRACE", exact: true })), { timeout: 3000 }); // lazy panels
  fireEvent.click(screen.getByRole("button", { name: "VERDICT", exact: true }));
  await waitFor(() => assert(screen.getByText(after.tradeoffs[0])), { timeout: 3000 }); // the plan, in VERDICT
  fireEvent.click(screen.getByRole("button", { name: "TRACE", exact: true }));
  assert(screen.getByText("mcp_trace.log"));
  assert(document.querySelectorAll(".trace-line").length > 0);
  fireEvent.click(screen.getByRole("button", { name: "MONEY", exact: true }));
  assert(screen.getByText("THE MATH, LINE BY LINE."));
  assert(screen.getByText(new RegExp(after.numbers.math.at(-1).label)));
  fireEvent.click(screen.getByRole("button", { name: "Close dialog", exact: true }));
  assert(!screen.queryByText("mcp_trace.log"));
  // On / Off only: Off unplugs the server for real; there is no Auto.
  fireEvent.click(screen.getByRole("button", { name: "Manage Schedule" }));
  assert(!screen.queryByRole("button", { name: "Auto", exact: true }));
  fireEvent.click(screen.getByRole("button", { name: "Off", exact: true }));
  await waitFor(() => assert(fake.calls.includes("POST /servers/calendar/unplug")));
  fireEvent.click(screen.getByRole("button", { name: "Close dialog", exact: true }));
  // A purchase gets the item card.
  fireEvent.click(screen.getByRole("button", { name: "A new table", exact: true }));
  await waitFor(() => assert(screen.getByRole("heading", { name: "FIRST, WHAT IT COSTS." })), { timeout: 5000 });
  assert.equal(document.querySelectorAll(".journey-card").length, 1);
  // Reset: the demo starts again without the budget.
  fireEvent.keyDown(window, { key: "d" });
  fireEvent.click(screen.getByRole("button", { name: "Reset demo" }));
  await waitFor(() => assert(fake.calls.includes("POST /servers/finance/unplug")));
  assert(!screen.queryByRole("dialog"));
  assert(!screen.queryByRole("heading", { name: "ALL TOGETHER NOW." }));
  assert.equal(screen.getByRole("textbox", { name: "What would you like to decide?" }).value, "");
  assert.equal(errors.length, 0, errors.join("\n"));
  console.log(
    "PASS: DOM interaction checks against real backend responses — hydrated registry, trip cards from the engine's breakdown, real Finance hot-plug and tools, masked statement upload with a read-only balance, engine verdict and plan, insights from real records, On/Off without Auto, product card, reset; no React console errors. Visual browser QA not performed.",
  );
} finally {
  cleanup();
  console.error = old;
  await vite.close();
  dom.window.close();
}
