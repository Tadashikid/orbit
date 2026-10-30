import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import postcss from "postcss";
import Specificity from "@bramus/specificity";
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
// DOM/CSS cascade audit, not a visual browser/layout test. Read the actual
// rendered components and stylesheet selectors, custom properties, specificity,
// responsive rules and interaction states. No assertion relies on a token name.
const sources = await Promise.all(
  ["tokens", "app", "journey", "motion", "legibility"].map((name) =>
    readFile(`src/styles/${name}.css`, "utf8"),
  ),
);
let rules = [];
const addRules = (source) => {
  postcss.parse(source).walkRules((rule) => {
    for (const selector of postcss.list.comma(rule.selector)) {
      const s = Specificity.calculate(selector)[0].value;
      rules.push({
        selector,
        media: [],
        rank: s.a * 1e6 + s.b * 1e3 + s.c,
        order: order++,
        declarations: rule.nodes.filter((n) => n.type === "decl"),
      });
    }
  });
};
let order = 0;
for (const source of sources) {
  postcss.parse(source).walkRules((rule) => {
    const media = [];
    for (let p = rule.parent; p; p = p.parent) {
      if (p.type === "atrule" && p.name.includes("keyframes")) return;
      if (p.type === "atrule" && p.name === "media") media.push(p.params);
    }
    for (const selector of postcss.list.comma(rule.selector)) {
      const s = Specificity.calculate(selector)[0].value;
      rules.push({
        selector,
        media,
        rank: s.a * 1e6 + s.b * 1e3 + s.c,
        order: order++,
        declarations: rule.nodes.filter((n) => n.type === "decl"),
      });
    }
  });
}
let width = 1440;
let cache = new Map();
const mediaMatches = (query) =>
  !(/min-width:\s*(\d+)px/.test(query) && width < +RegExp.$1) &&
  !(/max-width:\s*(\d+)px/.test(query) && width > +RegExp.$1) &&
  !query.includes("no-preference");
const match = (element, selector, pseudo) => {
  const ps = selector.match(/::?(before|after|placeholder)\b/);
  if ((ps?.[1] || "") !== pseudo) return false;
  selector = selector
    .replace(/::?(before|after|placeholder)\b/g, "")
    .replace(
      /:focus-visible|:focus(?!-)|:focus-within/g,
      "[data-contrast-focus]",
    )
    .replace(/:hover/g, "[data-contrast-hover]")
    .replace(/:active/g, "[data-contrast-active]");
  return element.matches(selector);
};
const resolve = (value, vars, depth = 0) => {
  assert(depth < 20, `Unresolved/cyclic custom property: ${value}`);
  return value.replace(
    /var\((--[\w-]+)(?:,\s*([^()]+))?\)/g,
    (_, key, fallback) => {
      assert(vars[key] || fallback, `Missing custom property ${key}`);
      return resolve(vars[key] || fallback, vars, depth + 1);
    },
  );
};
function styleFor(element, pseudo = "") {
  if (!element)
    return { vars: {}, color: "#10261f", font: 16, family: "", opacity: 1 };
  const key = `${element.dataset.contrastId}:${pseudo}`;
  if (cache.has(key)) return cache.get(key);
  const parent = styleFor(pseudo ? element : element.parentElement);
  const chosen = new Map();
  const write = (prop, value, rank, sequence, important) => {
    const prev = chosen.get(prop);
    const score = (important ? 1e9 : 0) + rank;
    if (
      !prev ||
      score > prev.score ||
      (score === prev.score && sequence >= prev.sequence)
    )
      chosen.set(prop, { value, score, sequence });
  };
  for (const rule of rules) {
    if (
      !rule.media.every(mediaMatches) ||
      !match(element, rule.selector, pseudo)
    )
      continue;
    for (const d of rule.declarations) {
      write(d.prop, d.value, rule.rank, rule.order, d.important);
      if (d.prop === "background")
        write("background-color", d.value, rule.rank, rule.order, d.important);
      if (d.prop === "font" && d.value === "inherit") {
        write("font-size", "inherit", rule.rank, rule.order, d.important);
        write("font-family", "inherit", rule.rank, rule.order, d.important);
      }
    }
  }
  if (!pseudo)
    for (const prop of element.style) {
      write(
        prop,
        element.style.getPropertyValue(prop),
        1e8,
        1e8,
        element.style.getPropertyPriority(prop),
      );
    }
  const raw = { ...parent.vars };
  for (const [prop, { value }] of chosen)
    if (prop.startsWith("--")) raw[prop] = value;
  const vars = Object.fromEntries(
    Object.entries(raw).map(([k, v]) => [k, resolve(v, raw)]),
  );
  const read = (prop, fallback) => {
    const value = chosen.get(prop)?.value;
    return !value || value === "inherit" ? fallback : resolve(value, vars);
  };
  const size = read("font-size", `${parent.font}px`);
  const font = size.endsWith("rem")
    ? parseFloat(size) * 16
    : size.endsWith("em")
      ? parseFloat(size) * parent.font
      : parseFloat(size) || parent.font;
  const style = {
    vars,
    color: read("color", parent.color),
    font,
    family: read("font-family", parent.family),
    opacity: +read("opacity", "1") * parent.opacity,
    bg: read("background-color", "transparent"),
    hidden:
      parent.hidden ||
      read("display", "") === "none" ||
      read("visibility", "") === "hidden" ||
      element.hidden,
    border: read("border-color", read("border", "")),
    outline: read("outline-color", read("outline", "")),
    transform: read("transform", "none"),
  };
  if (style.color === "currentColor") style.color = parent.color;
  cache.set(key, style);
  return style;
}
function rgb(value) {
  if (value === "transparent") return [0, 0, 0, 0];
  if (value.startsWith("color-mix")) {
    const m = value.match(
      /color-mix\(in srgb,\s*(#[a-f\d]+)\s*([\d.]+)%,\s*transparent\)/i,
    );
    assert(m, `Unsupported color mix: ${value}`);
    return [...rgb(m[1]).slice(0, 3), +m[2] / 100];
  }
  const hex = value.match(/#[a-f\d]{6}/i)?.[0];
  if (hex)
    return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).concat(1);
  const numbers = value
    .match(/^rgba?\(([^)]+)\)/)?.[1]
    .split(/[,\s/]+/)
    .map(Number);
  assert(numbers?.length >= 3, `Unsupported color: ${value}`);
  return [...numbers.slice(0, 3), numbers[3] ?? 1];
}
const blend = (foreground, background) =>
  foreground
    .slice(0, 3)
    .map((n, i) => n * foreground[3] + background[i] * (1 - foreground[3]))
    .concat(1);
function background(element) {
  if (!element) return rgb("#fcf4df");
  return blend(rgb(styleFor(element).bg), background(element.parentElement));
}
const luminance = (color) =>
  color.slice(0, 3).reduce((sum, v, i) => {
    v /= 255;
    return (
      sum +
      [0.2126, 0.7152, 0.0722][i] *
        (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
    );
  }, 0);
const contrast = (a, b) =>
  (Math.max(luminance(a), luminance(b)) + 0.05) /
  (Math.min(luminance(a), luminance(b)) + 0.05);
const errors = [];
const consoleErrors = [];
const originalError = console.error;
console.error = (...args) => consoleErrors.push(args.join(" "));
let checks = 0;
let state = "default";
function check(element, value, bg, target, kind) {
  const s = styleFor(element);
  const foreground = rgb(value);
  foreground[3] *= s.opacity;
  const ratio = contrast(blend(foreground, bg), bg);
  checks++;
  if (ratio + 0.001 < target)
    errors.push(
      `${width}px ${state}: ${kind} ${element.className.baseVal ?? element.className} (${element.textContent.trim().slice(0, 45)}) ${ratio.toFixed(2)}:1 < ${target}:1`,
    );
}
function scan() {
  cache = new Map();
  document
    .querySelectorAll("*")
    .forEach((e, i) => (e.dataset.contrastId = String(i)));
  for (const e of document.querySelectorAll(
    ".journey-card *, .trip-summary *, .source-dock *",
  )) {
    const s = styleFor(e);
    if (s.hidden || s.opacity === 0 || e.closest(".sr-only")) continue;
    const text = [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim(),
    );
    const bg = background(e);
    if (text) {
      check(e, s.color, bg, 4.5, "text");
      const minimum = /JetBrains|Consolas/.test(s.family) ? 12 : 14;
      if (s.font < minimum)
        errors.push(
          `${width}px ${state}: ${e.className} (${e.textContent.trim().slice(0, 35)}) font ${s.font}px < ${minimum}px`,
        );
    }
    if (e.tagName.toLowerCase() === "svg") check(e, s.color, bg, 3, "icon");
    if (e.matches(".dock-indicator"))
      check(e, s.bg, background(e.parentElement), 3, "status indicator");
    const button = e.closest("button");
    if (button && text && state !== "default" && !button.disabled) {
      const sweep = styleFor(button, "before");
      if (sweep.bg !== "transparent" && sweep.transform.includes("scaleX(1)"))
        check(
          e,
          s.color,
          blend(rgb(sweep.bg), background(button)),
          4.5,
          "text during fill sweep",
        );
    }
    // Borders that convey input boundaries and focus states are functional UI.
    // Decorative card/divider borders and text-labelled button fills are not
    // subject to WCAG 1.4.11; their readable labels identify their purpose.
    if (e.matches("input,textarea,select"))
      check(e, s.border, bg, 3, "input boundary");
    if (e.matches("button[data-contrast-focus]") && s.outline) {
      const adjacent = e.matches(".journey-stay .legible-cream-button")
        ? rgb("#10261f")
        : background(e.parentElement);
      check(e, s.outline, adjacent, 3, "focus outline");
    }
  }
}
try {
  const { default: PlanJourney } = await vite.ssrLoadModule(
    "/src/screens/PlanJourney.tsx",
  );
  const { default: SourceDock } = await vite.ssrLoadModule(
    "/src/components/SourceDock.tsx",
  );
  // A real answer (tests/fixtures/backend.json): Goa with Finance on, so every card and the summary are filled.
  const { api, presentVerdict } = await vite.ssrLoadModule("/src/api.ts");
  const { fakeBackend, HERO } = await import("./fake-backend.mjs");
  globalThis.fetch = fakeBackend({ finance: true, statement: true }).fetch;
  const { servers } = await api.servers();
  const verdict = presentVerdict(await api.decide(HERO, servers));
  const statement = await api.statement();
  const noop = () => {};
  render(
    React.createElement(
      React.Fragment,
      null,
      React.createElement(PlanJourney, {
        verdict,
        previous: null,
        servers,
        statement,
        today: "2026-10-08",
        busy: false,
        onConnect: noop,
        onSetup: noop,
        onBalance: noop,
        onInsights: noop,
      }),
      React.createElement(SourceDock, {
        servers,
        onPermission: noop,
        onConnect: noop,
        active: [],
        returned: [],
        phase: "done",
      }),
    ),
  );
  assert.equal(document.querySelectorAll(".journey-card").length, 3);
  const classes = new Set(
    [...document.querySelectorAll("*")].flatMap((e) => [...e.classList]),
  );
  rules = rules.filter((r) => {
    const names = [...r.selector.matchAll(/\.([\w-]+)/g)].map((m) => m[1]);
    return !names.length || names.some((name) => classes.has(name));
  });
  // Negative controls recreate each reported regression. The audit must flag
  // them before checking the fixed styles, including low-contrast child text.
  const ruleCount = rules.length;
  addRules(`
    .journey-card.journey-flight .flashcard-tab .tab-budget-label { color: #10261f !important; }
    .journey-card.journey-flight .route-display > div > span { color: #10261f !important; }
    .journey-card.journey-flight .flight-notice p { color: #10261f !important; }
  `);
  scan();
  for (const selector of [
    "tab-budget-label",
    "Bengaluru",
    "Goa",
    "The cheapest fares",
  ])
    assert(
      errors.some((message) => message.includes(selector)),
      `Audit did not detect ${selector}`,
    );
  rules.length = ruleCount;
  errors.length = 0;
  checks = 0;
  for (width of [1440, 375])
    for (state of ["default", "hover", "focus", "disabled"]) {
      document
        .querySelectorAll("[data-contrast-hover],[data-contrast-focus]")
        .forEach((e) => {
          delete e.dataset.contrastHover;
          delete e.dataset.contrastFocus;
        });
      document.querySelectorAll(".journey-card,button").forEach((e) => {
        if (state === "hover") e.dataset.contrastHover = "";
        if (state === "focus") {
          e.dataset.contrastFocus = "";
          for (let p = e.parentElement; p; p = p.parentElement)
            p.dataset.contrastFocus = "";
        }
        if (e.tagName === "BUTTON") e.disabled = state === "disabled";
      });
      scan();
    }
  assert.deepEqual(errors, [], errors.join("\n"));
  assert.deepEqual(consoleErrors, [], "React console errors");
  console.log(
    `PASS: ${checks} contrast checks — flashcards 01/02/03, final summary, rail and tooltips; 1440px/375px; default/hover/focus/disabled; text >=4.5:1, icons and functional UI >=3:1, minimum text sizes. CSS/DOM audit; visual browser QA not performed.`,
  );
} finally {
  cleanup();
  console.error = originalError;
  await vite.close();
  dom.window.close();
}
