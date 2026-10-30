import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { createServer } from "vite";
import React from "react";
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
  matches: false,
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
try {
  const { default: EvidenceGraph } = await vite.ssrLoadModule(
    "/src/components/EvidenceGraph.tsx",
  );
  // A real answer (tests/fixtures/backend.json) with Finance on and Manu's statement loaded.
  const { api, presentVerdict } = await vite.ssrLoadModule("/src/api.ts");
  const { fakeBackend, HERO } = await import("./fake-backend.mjs");
  const fake = fakeBackend({ finance: true, statement: true });
  globalThis.fetch = fake.fetch;
  window.fetch = fake.fetch;
  const { servers } = await api.servers();
  const result = await api.decide(HERO, servers);
  const verdict = presentVerdict(result);
  const returned = [
    ...new Set(
      verdict.evidence.map((e) => servers.find((s) => s.name === e.server).id),
    ),
  ];
  const before = JSON.stringify({ result, servers });
  const calls = fake.calls.length;
  let skips = 0;
  const props = {
    servers,
    phase: "done",
    active: returned,
    returned,
    verdict,
    question: verdict.question,
    highlight: "",
    skip: () => skips++,
    slow: false,
  };
  try {
    const view = render(React.createElement(EvidenceGraph, props));
    const replay = screen.getByRole("button", { name: "Replay flow" });
    assert(replay.disabled);
    assert(document.querySelector(".mobile-flow-question .graph-ripple"));
    assert.equal(
      document.querySelectorAll(".mobile-flow-source .graph-ripple").length,
      0,
    );
    await waitFor(
      () =>
        assert.equal(
          document.querySelectorAll(".mobile-flow-source .graph-ripples")
            .length,
          returned.length,
        ),
      { timeout: 1500 },
    );
    for (const source of document.querySelectorAll(".mobile-flow-source")) {
      if (!source.classList.contains("returned"))
        assert(!source.querySelector(".graph-ripple"));
    }
    await waitFor(
      () =>
        assert(document.querySelector(".mobile-flow-verdict .graph-ripple")),
      { timeout: 1500 },
    );
    await waitFor(() => assert(!replay.disabled), { timeout: 1800 });
    // Finite rings settle, instead of competing with the readable evidence indefinitely.
    await waitFor(
      () => {
        for (const ring of document.querySelectorAll(".graph-ripple"))
          assert.equal(ring.style.opacity, "0");
      },
      { timeout: 1500 },
    );
    const evidenceText = document.querySelector(".mobile-flow").textContent;
    fireEvent.click(replay);
    assert(replay.disabled);
    assert.equal(
      document.querySelectorAll(".mobile-flow-source .graph-ripple").length,
      0,
    );
    await waitFor(() => assert(!replay.disabled), { timeout: 3000 });
    assert.equal(
      document.querySelector(".mobile-flow").textContent,
      evidenceText,
    );
    assert.equal(JSON.stringify({ result, servers }), before);
    assert.equal(fake.calls.length, calls); // replaying the graph never calls the backend
    assert.equal(skips, 0);
    // Receipt highlights must not restart the presentation.
    view.rerender(
      React.createElement(EvidenceGraph, { ...props, highlight: "Finance" }),
    );
    assert(!replay.disabled);
    fireEvent.click(replay);
    view.unmount();
    assert.equal(errors.length, 0, errors.join("\n"));
    console.log(
      "PASS: motion checks — ordered finite graph ripples, skipped-source exclusion, replay without new reads or result changes, and cleanup; no React console errors.",
    );
  } finally {
    /* nothing to restore: the fake backend stays in place for the full-page run */
  }
  // Exercise the full page with motion enabled, including counters and source feedback.
  const { default: App } = await vite.ssrLoadModule("/src/App.tsx");
  const app = render(React.createElement(App));
  await waitFor(
    () =>
      assert.equal(
        document.querySelector(".header-budget").textContent,
        "Rs 54,263",
      ),
    { timeout: 2000 },
  );
  assert(screen.getByRole("heading", { name: /BIG PLANS.CLEAR ANSWERS/ }));
  fireEvent.click(
    screen.getByRole("button", { name: "A Goa weekend", exact: true }),
  );
  await waitFor(
    () => assert(screen.getByRole("button", { name: /Your plan is ready/ })),
    { timeout: 5000 },
  );
  await waitFor(
    () =>
      assert(
        document.querySelector(".summary-total").textContent.includes("11,999"),
      ),
    { timeout: 2000 },
  );
  const oldPermission = document.querySelector(
    '.dock-icon[data-source-id="calendar"]',
  ).className;
  fireEvent.click(screen.getByRole("button", { name: "Manage Schedule" }));
  fireEvent.click(screen.getByRole("button", { name: "Off", exact: true }));
  fireEvent.click(
    screen.getByRole("button", { name: "Close dialog", exact: true }),
  );
  assert(oldPermission.includes("enabled"));
  await waitFor(() => // Off is a round trip to the backend registry (unplug), then the dock updates
    assert(
      !document
        .querySelector('.dock-icon[data-source-id="calendar"]')
        .className.includes("enabled"),
    ),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "A Goa weekend", exact: true }),
  );
  await waitFor(
    () => assert(screen.getByRole("button", { name: /Your plan is ready/ })),
    { timeout: 5000 },
  );
  assert(
    !document
      .querySelector('.dock-icon[data-source-id="calendar"] svg')
      .classList.contains("lucide-check"),
  );
  // Check the physical cover endpoints and non-sticky fallback without changing layout code.
  const stack = document.querySelector(".flashcard-stack");
  const cards = [...stack.querySelectorAll(".journey-card")];
  cards.forEach((card) =>
    assert.equal(
      card.style.transform,
      "",
      "Framer must not override the scroll-driven CSS transform",
    ),
  );
  stack.style.gap = "90px";
  stack.style.paddingBottom = "80px";
  Object.defineProperty(stack, "offsetHeight", {
    configurable: true,
    get: () => 1730,
  });
  stack.getBoundingClientRect = () => ({ top: 1000 - window.scrollY });
  cards.forEach((card, i) => {
    card.style.position = "sticky";
    card.style.top = `${36 + i * 34}px`;
    Object.defineProperty(card, "offsetHeight", {
      configurable: true,
      get: () => 490,
    });
  });
  Object.defineProperty(window, "scrollY", {
    configurable: true,
    value: 1550,
    writable: true,
  });
  fireEvent.scroll(window);
  await waitFor(() =>
    assert.equal(cards[0].style.getPropertyValue("--cover-scale"), "0.96"),
  );
  assert.equal(cards[0].style.getPropertyValue("--cover-y"), "-12px");
  assert.equal(cards[0].style.getPropertyValue("--cover-brightness"), "0.88");
  assert.equal(cards[0].style.getPropertyValue("--cover-blur"), "1.5px");
  window.scrollY = 0;
  fireEvent.scroll(window);
  await waitFor(() =>
    assert.equal(cards[0].style.getPropertyValue("--cover-scale"), "1"),
  );
  cards.forEach((card) => {
    card.style.position = "relative";
  });
  window.scrollY = 1550;
  fireEvent.scroll(window);
  await waitFor(() =>
    assert.equal(cards[0].style.getPropertyValue("--cover-blur"), "0px"),
  );
  assert.equal(cards[0].style.getPropertyValue("--cover-scale"), "1");
  assert.equal(errors.length, 0, errors.join("\n"));
  app.unmount();
  console.log(
    "PASS: full-page motion smoke — counters settle at unchanged figures, headline/copy persist, source controls remain functional, and denied sources never show read confirmations; no React console errors.",
  );
} finally {
  cleanup();
  console.error = old;
  await vite.close();
  dom.window.close();
}
