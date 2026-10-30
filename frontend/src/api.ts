import type {
  DecisionResult,
  Server,
  Source,
  StatementInfo,
  TraceLine,
  Verdict,
  VerdictContract,
  VerdictKind,
} from "./types";
// The Orbit FastAPI backend (backend/main.py), reached through the Vite proxy: /api/* -> 127.0.0.1:8000/*.
// The backend owns every number, the server registry, Guardian and the audit trace; this file only translates.
interface BackendServer {
  name: string;
  plugged: boolean;
  status: Server["status"];
  tools: { name: string; description: string; read_only: boolean }[];
}
interface BackendTrace {
  server: string;
  tool: string;
  ok: boolean;
  ms: number;
  by: "gemini" | "rules";
  guardian: "allowed" | "blocked" | "needs_approval";
  ts?: string;
}
interface BackendAsk {
  verdict: VerdictContract;
  explanation: string | null;
  trace: BackendTrace[];
  intent: DecisionResult["intent"];
  offline: Record<string, string>;
}
// POST /agent streams these as server-sent events. A tool event for Orbit's own check_plan carries its full answer.
type AgentEvent =
  | { type: "session"; id: string }
  | { type: "step" | "message"; text: string }
  | { type: "done" }
  | ({ type: "tool"; args?: Record<string, unknown>; error?: string; answer?: BackendAsk } & BackendTrace);
export interface OrbitApi {
  // `onStep` gets a short, human line for each step the agent takes, as it happens.
  decide(question: string, servers: Server[], onStep?: (step: string) => void): Promise<DecisionResult>;
  newConversation(): void;
  // The demo login: the backend sets an httpOnly cookie; the UI only learns who is signed in.
  me(): Promise<string | null>;
  login(email: string, password: string): Promise<string>;
  logout(): Promise<void>;
  servers(): Promise<{ servers: Server[]; today: string }>;
  setSource(id: string, on: boolean): Promise<{ servers: Server[]; today: string }>;
  statement(): Promise<StatementInfo | null>;
  uploadStatement(input: File | { sample: string }): Promise<StatementInfo>;
  samples(): Promise<string[]>;
}
// Backend server name -> how the UI names it. A server the UI doesn't know keeps its own name (generic icon).
const UI: Record<string, { id: string; name: string }> = {
  calendar: { id: "calendar", name: "Calendar" },
  gmail: { id: "tasks", name: "Tasks" },
  finance: { id: "finance", name: "Finance" },
  travel: { id: "travel", name: "Travel" },
  price: { id: "price", name: "Price Check" },
  orbit: { id: "orbit", name: "Orbit" },
};
const ui = (backend: string) => UI[backend] ?? { id: backend, name: backend };
const backendName = (id: string) =>
  Object.keys(UI).find((k) => UI[k].id === id) ?? id;
const SOURCES: Record<string, Source> = {
  live: "live",
  cached: "cached",
  seeded: "seeded",
  statement_csv: "statement",
  user_estimate: "estimate",
  error: "error",
};
const VERDICTS: VerdictKind[] = ["yes", "yes_with_conditions", "risky", "no", "insufficient_data", "info"];
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}
async function send(path: string, body?: unknown): Promise<Response> {
  try {
    return await fetch(
      `/api${path}`,
      body === undefined
        ? undefined
        : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    );
  } catch {
    throw new ApiError("Can't reach Orbit. Is the backend running (backend/main.py)?", 0);
  }
}
function parse(text: string): unknown {
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return null; // not JSON: reported by the caller
  }
}
function failure(data: unknown, status: number) {
  const detail = (data as { detail?: unknown } | null)?.detail;
  const message = typeof detail === "string"
    ? detail
    : Array.isArray(detail)
      ? detail.map((d: { msg?: string }) => d.msg).join("; ")
      : `Orbit API error ${status}`;
  return new ApiError(message, status);
}
async function call<T>(path: string, body?: unknown): Promise<T> {
  const res = await send(path, body);
  const data = parse(await res.text());
  if (!res.ok) throw failure(data, res.status);
  return data as T;
}
// Server-sent events over a POST (EventSource only does GET): one JSON object per "data: " line.
async function stream(path: string, body: unknown, onEvent: (e: AgentEvent) => void) {
  const res = await send(path, body);
  if (!res.ok || !res.body) throw failure(parse(await res.text()), res.status);
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    buffer += value ?? "";
    const chunks = buffer.split("\n\n");
    buffer = done ? "" : (chunks.pop() ?? "");
    for (const chunk of chunks)
      for (const line of chunk.split("\n"))
        if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)) as AgentEvent);
    if (done) return;
  }
}
// The conversation this tab is in. The backend keeps the turns; the UI only remembers which conversation it is.
let session: string | null = null;
const stepLabel = (e: Extract<AgentEvent, { type: "tool" }>) =>
  e.guardian !== "allowed"
    ? `Guardian stopped ${e.tool}`
    : e.server === "orbit"
      ? `Checked: ${String(e.args?.question ?? "your plan")}`
      : `Read ${ui(e.server).name}`;
// An agent answer that checked no plan ("what's on my calendar?") still shows as an answer card.
const infoAnswer = (question: string, text: string): BackendAsk => ({
  verdict: {
    question,
    verdict: "info",
    headline: text || "Done.",
    numbers: {
      balance: null,
      trip_cost: { low: null, high: null },
      monthly_commitments: null,
      remaining: { low: null, high: null },
    },
    evidence: [],
    tradeoffs: [],
    not_read: [],
  },
  explanation: null,
  trace: [],
  intent: null,
  offline: {},
});
const toServers = (d: { servers: BackendServer[]; today: string }) => ({
  today: d.today,
  servers: d.servers.map((s) => ({
    ...ui(s.name),
    status: s.status,
    permission: s.plugged ? ("allow" as const) : ("off" as const),
    tools: s.tools.map((t) => ({
      name: t.name,
      description: t.description,
      kind: t.read_only ? ("read" as const) : ("write" as const),
    })),
  })),
});
const toTrace = (t: BackendTrace): TraceLine => ({
  ts: t.ts ?? "",
  server: ui(t.server).name,
  tool:
    `tools/call ${t.tool} · ${t.by === "gemini" ? "chosen by Gemini" : "rules planner"}` +
    (t.guardian === "needs_approval"
      ? " · write blocked by Guardian"
      : t.guardian === "blocked"
        ? " · blocked by Guardian"
        : ""),
  ms: t.ms ?? 0,
  status: t.guardian !== "allowed" ? "denied" : t.ok ? "ok" : "error",
});
// UI-only: how fresh the data behind an answer is. The engine has no confidence score; this never changes a number.
export function confidence(w: VerdictContract): Verdict["confidence"] {
  const s = w.evidence.map((e) => e.source);
  if (w.verdict === "insufficient_data" || s.includes("error") || s.includes("seeded")) return "low";
  if (s.includes("cached") || s.includes("estimate")) return "medium";
  return "high";
}
export function toResult(r: BackendAsk, servers: Server[]): DecisionResult {
  const v = r?.verdict;
  if (
    !v ||
    !VERDICTS.includes(v.verdict) ||
    typeof v.headline !== "string" ||
    !v.numbers ||
    !Array.isArray(v.evidence) ||
    !Array.isArray(v.tradeoffs) ||
    !Array.isArray(v.not_read)
  )
    throw new ApiError("Orbit sent an answer this screen can't read.", 200);
  const off = new Set(
    servers.filter((s) => s.status !== "connected" || s.permission === "off").map((s) => s.id),
  );
  const wire: VerdictContract = {
    ...v,
    evidence: v.evidence.map((e) => ({
      ...e,
      server: ui(e.server).name,
      source: SOURCES[e.source] ?? "error",
    })),
    not_read: v.not_read.map(
      (n) => `${ui(n).name}: ${off.has(ui(n).id) ? "switched off" : "not needed for this question"}`,
    ),
  };
  return {
    wire,
    trace: (r.trace ?? []).map(toTrace),
    confidence: confidence(wire),
    explanation: r.explanation ?? null,
    intent: r.intent ?? null,
    offline: Object.keys(r.offline ?? {}).map((n) => ui(n).name),
  };
}
export const api: OrbitApi = {
  async decide(question, servers, onStep) {
    // The agent loop: it may check several plans; the screen shows the last one, the agent's reply as the wording.
    const plans: BackendAsk[] = [];
    const trace: BackendTrace[] = [];
    let reply = "";
    await stream("/agent", { goal: question, ...(session ? { session_id: session } : {}) }, (e) => {
      if (e.type === "session") session = e.id;
      else if (e.type === "step") onStep?.(e.text);
      else if (e.type === "message") reply = e.text;
      else if (e.type === "tool") {
        trace.push(e, ...(e.answer?.trace ?? []));
        if (e.answer) plans.push(e.answer);
        onStep?.(stepLabel(e));
      }
    });
    const shown = plans.at(-1) ?? infoAnswer(question, reply);
    const wording = reply && reply !== shown.verdict.headline ? reply : shown.explanation;
    return toResult({ ...shown, explanation: wording, trace }, servers);
  },
  newConversation() {
    session = null;
  },
  async me() {
    try {
      return (await call<{ email: string }>("/me")).email;
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return null;
      throw e;
    }
  },
  async login(email, password) {
    return (await call<{ email: string }>("/login", { email, password })).email;
  },
  async logout() {
    session = null;
    await call("/logout", {});
  },
  async servers() {
    return toServers(await call("/servers"));
  },
  async setSource(id, on) {
    return toServers(await call(`/servers/${backendName(id)}/${on ? "plug" : "unplug"}`, {}));
  },
  async statement() {
    try {
      return await call<StatementInfo>("/statement");
    } catch (e) {
      // 409: Finance is off; 502: Finance has no statement yet. Either way there's nothing to show.
      if (e instanceof ApiError && (e.status === 409 || e.status === 502)) return null;
      throw e;
    }
  },
  async uploadStatement(input) {
    return call<StatementInfo>("/statement", input instanceof File ? { csv: await input.text() } : input);
  },
  async samples() {
    return (await call<{ samples: string[] }>("/statement/samples")).samples;
  },
};
export const presentVerdict = (result: DecisionResult): Verdict => ({
  ...result.wire,
  confidence: result.confidence,
  explanation: result.explanation,
  intent: result.intent,
});
