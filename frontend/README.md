# Orbit frontend

React + Vite + TypeScript + Tailwind, React Flow, Framer Motion, lucide-react.

## Run locally

The UI talks to the Orbit backend through Vite's proxy (`/api/*` → `http://127.0.0.1:8000`), so start the backend first, from the repository root:

```bash
.venv\Scripts\python run_servers.py
.venv\Scripts\python backend\main.py
```

Then, in this folder:

```bash
npm ci
npm run dev
```

Open http://127.0.0.1:4173. `npm run build` checks TypeScript and builds `dist/`. The dev server listens on this machine only; run `npm run dev -- --host` to show it on your network. `ORBIT_API=http://127.0.0.1:8300 npm run dev` points it at another backend.

## Consumer-facing redesign

Styling-only forest update: `--forest-900` #173F37, `--forest-800` #194643, `--forest-600` #2B6A5F, `--sand-300` #CAB298 and `--paper` #FCF4DF use flat-fill samples from the reference. `--mint-300` #A8E6C6, `--mint-100` #D6F3E3 and `--ink` #10261F keep highlights and text readable. Green surfaces are solid dark fills; mint is reserved for text, dots and thin motion highlights. The original Anton / Space Grotesk / JetBrains Mono typography, radii, spacing, copy, routes and data remain. Borders are 1px hairlines with layered shadows; the masked grid uses 48px cells and 11% forest lines with up to 8px scroll parallax. Static SVG grain and low-opacity contour lines stay behind the existing interface.

The landing view exposes one question and three short examples. After asking, the flow is Flights → Stay → Other costs → one consolidated summary. Desktop cards stack on scroll. On small or short screens, readable cards reveal as you scroll without sticky content clipping; reduced motion disables those effects. Technical graph, receipt, trace and detailed numbers load only after **View detailed insights**.

Motion is presentation only: staggered headline masks, ask/chip/rail entry, scroll-linked covered-card transforms (0.96 scale, -12px lift, 0.88 brightness, up to 1.5px blur), 800ms counters with reserved final widths, one verdict/budget settle and ring, pointer-only magnetic buttons and card tilt, rail indicator motion, and header scroll progress. Rail confirmations follow returned evidence, never a guessed read. Idle pulses and the 56s contour drift pause in hidden tabs. Reduced motion switches to static information and stops the ambient layer. **Replay flow** still presents existing graph evidence without new reads or result changes.

## What the screens show

Every number comes from the backend's engine (`backend/engine.py`); the UI never calculates a verdict.

- **Cards** follow the question: a trip gets Flights → Stay → Other costs; a purchase gets one item card (the cheapest new offers from mainstream stores); a night out gets one outing card (per person × people); a general question gets a plain answer. Each card's amount is the engine's `numbers.breakdown`; its tab says where it came from (live, saved or sample prices, or your estimate). Flights are real fares from the Travel MCP; the stay is real 2–4 star hotel prices (Travel `search_hotels`, hostels left out); other costs are your cost-table estimates.
- **The summary** shows the engine's verdict (yes / only if / risky / not yet / need more data), your balance, monthly commitments, and what's left before payday. The engine's plan is in **View detailed insights** → VERDICT.
- **The icon dock** is On / Off per source: On plugs the MCP server into the backend registry, Off unplugs it. There is no Auto.
- **Your balance** is the running balance on the last row of the statement you upload. It is read-only; upload a newer statement to change it. **Add a statement** uploads a CSV (demo ones are in `data/samples/`); the backend masks it in memory and keeps only date, category, debit, credit and balance.
- **View detailed insights** holds the technical detail: the evidence graph, the verdict with every evidence row and its source, the receipt (what was read and not read, writes blocked), the MCP trace as the backend recorded it, and MONEY: the line-by-line math, cash on the day, the lowest point before payday, monthly spending by category, bills and SIPs, and how the spending forecast was chosen and back-tested.
- **Safety:** when the engine ignores instructions hidden in an email, a notice says so and the insights show the flagged finding.
- **Confidence** is a UI-only label for how fresh the data is (live and your statement: high; saved prices or estimates: medium; sample data or a failed source: low). It never changes a number.

## Demo

1. Ask the Goa question. With Finance off, the cards show real fares and hotel prices; the money isn't checked.
2. Choose **Add your budget** → **Connect budget** (the real hot-plug; see the tools Finance announces).
3. **Add a statement** → choose a CSV from `data/samples/` → **Continue** → **Done**.
4. **Check my plan again**: the verdict now includes the money and a plan.
5. **View detailed insights** for the graph, receipt, trace and the math.
6. Press D for the demo drawer: run the hero question, connect/disconnect Finance, slow animations, reset.

## Integration boundary

`src/api.ts` is the only file that talks to the backend: `POST /ask`, `GET /servers`, `POST /servers/{name}/plug|unplug`, `GET`/`POST /statement` and `GET /statement/samples`, translated into the UI's types (`src/types.ts`). It maps the backend's server names to the UI's (`gmail` → Tasks, `price` → Price Check), its evidence sources (`statement_csv` → your statement, `user_estimate` → estimate) and its trace rows; it rejects a malformed answer instead of showing invented zeros, and says so when the backend can't be reached. There is no mock fallback: if the backend is down, the UI says so.

## Verification

`npm test` runs the adapter contract (`tests/contracts.mjs`), the DOM journey (`tests/interactions.mjs`) and the motion checks (`tests/motion.mjs`) against **real backend responses**: `tests/fixtures/backend.json`, captured from `backend/main.py` (offline, seeded data) by `scripts/capture_ui_fixtures.py` and replayed by `tests/fake-backend.mjs`. Re-run the capture script when the API's responses change.

`node tests/contrast.mjs` audits the rendered Flights, Stay, Other costs, final summary and source rail against the actual CSS cascade at 1440px and 375px. It checks default, hover, focus and disabled styles, both sides of button fill sweeps, normal text at 4.5:1, meaningful icons/focus indicators at 3:1, and 12px mono / 14px body minimums. Negative controls reproduce the reported regressions to verify detection. This is a DOM/CSS audit, not a browser rendering or layout check; purely decorative dividers and card borders are excluded from WCAG 1.4.11. Foreground contexts use the five `--on-forest-*` / `--on-paper-*` tokens; sand captions use the darker primary paper token because the secondary token would fail AA on the existing sand fill.
