// Where a piece of evidence came from, as the backend labels it (statement = the user's uploaded statement,
// estimate = the cost table, error = a source that failed for this answer).
export type Source = "live" | "cached" | "seeded" | "statement" | "estimate" | "error";
export type Permission = "off" | "allow";
export interface Tool {
  name: string;
  description: string;
  kind: "read" | "write";
}
export interface Server {
  id: string;
  name: string;
  status: "connected" | "off" | "error";
  tools: Tool[];
  permission: Permission;
}
export interface Evidence {
  server: string;
  tool: string;
  finding: string;
  as_of: string;
  source: Source;
}
export type VerdictKind = "yes" | "yes_with_conditions" | "risky" | "no" | "insufficient_data" | "info";
export interface Range {
  low: number | null;
  high: number | null;
}
export interface MathRow {
  label: string;
  amount: number;
}
export interface Leg {
  from: string;
  to: string;
  date: string;
  airline: string;
  depart: string;
  arrive: string;
  price: number;
  stops?: number;
}
export interface Hotel {
  name: string;
  per_night: number;
  rating?: number | null;
  reviews?: number | null;
  stars?: number | null;
  link?: string | null;
}
export interface Offer {
  title: string;
  store: string;
  price: number;
  mrp?: number | null;
  rating?: number | null;
  reviews?: number | null;
  link?: string | null;
}
// One card's share of the cost, from the engine (backend/engine.py: numbers.breakdown).
export interface Part extends Range {
  key: "flight" | "stay" | "other" | "product" | "outing";
  source?: string | null;
  legs?: Leg[];
  nights?: number;
  days?: number;
  per_night?: [number, number] | null;
  hotel?: Hotel | null;
  offers?: Offer[];
  note?: string | null;
  per_person?: [number, number] | null;
  people?: number;
}
// The Orbit verdict as POST /ask returns it. The first fields are Section 8 of Orbit_TEAM_BRIEF.md; the rest is
// what the engine adds (the cash-flow projection, the line-by-line math and the per-card breakdown).
export interface VerdictContract {
  question: string;
  kind?: "trip" | "purchase" | "expense" | "savings_goal" | "other";
  verdict: VerdictKind;
  headline: string;
  numbers: {
    balance: number | null;
    trip_cost: Range;
    monthly_commitments: number | null;
    remaining: Range;
    safety_floor?: number | null;
    cash_on_day?: number | null;
    pay_day?: string | null;
    next_salary?: string | null;
    math?: MathRow[] | null;
    breakdown?: Part[] | null;
  };
  evidence: Evidence[];
  tradeoffs: string[];
  not_read: string[];
}
export interface Intent {
  kind: string;
  item: string | null;
  city: string | null;
  origin: string;
  dest: string | null;
  abroad: boolean;
  start: string | null;
  end: string | null;
  people: number;
  today: string;
}
// Frontend presentation metadata does not extend the wire payload.
export interface Verdict extends VerdictContract {
  confidence: "low" | "medium" | "high";
  explanation: string | null;
  intent: Intent | null;
}
export interface TraceLine {
  ts: string;
  server: string;
  tool: string;
  ms: number;
  status: "ok" | "denied" | "error";
}
export interface StatementInfo {
  balance: number;
  as_of: string;
  rows?: number;
  from?: string;
  receipt?: { rows_kept: number; from: string; to: string; kept_columns: string[]; dropped_columns: string[]; rejected: unknown[] };
  summary: {
    monthly_avg_spend: number;
    monthly_avg_by_category: Record<string, number>;
    monthly_commitments: number;
    recurring: { category: string; day_of_month: number; amount: number; type: "income" | "debit" }[];
    forecast: {
      method: string;
      trained_on: { from: string; to: string; days: number };
      backtest: null | {
        days: number;
        weekday_miss_per_3_days: number;
        flat_miss_per_3_days: number;
        chosen: "weekday" | "flat";
      };
    };
  };
}
// A hold the agent prepared (backend/main.py /actions). Nothing is confirmed until you approve it on screen.
export interface Approval {
  id: string;
  kind: "flight" | "stay" | "order";
  summary: string;
  amount: number;
  currency?: string; // "INR" unless a provider prices it otherwise (Duffel test fares: GBP / USD)
  expires_at: string;
  hash: string; // the version you saw; approving sends it back
  status: "pending" | "approving" | "confirmed" | "declined" | "expired" | "failed";
  outcome?: { reference?: string; payment?: string; error?: string };
}
export interface DecisionResult {
  approvals: Approval[];
  wire: VerdictContract;
  trace: TraceLine[];
  confidence: Verdict["confidence"];
  explanation: string | null;
  intent: Intent | null;
  offline: string[];
}
export type Phase =
  "idle" | "discovering" | "calling" | "collecting" | "done" | "error";
