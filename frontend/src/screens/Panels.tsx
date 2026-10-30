import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  Check,
  AlertTriangle,
  ShieldCheck,
  ArrowDownRight,
  Copy,
  Pause,
  Play,
  Wallet,
  LockKeyhole,
  Info,
  XCircle,
  Eye,
} from "lucide-react";
import { motion } from "framer-motion";
import {
  revealEase,
  useMotionPreferences,
} from "../hooks/useMotionPreferences";
import type {
  Server,
  Source,
  StatementInfo,
  TraceLine,
  Verdict,
  VerdictKind,
  Phase,
} from "../types";
import {
  AnimatedAmount,
  Button,
  Chip,
  Pill,
  TerminalCard,
  icons,
  money,
  shortDate,
  Skeleton,
} from "../components/ui";
const SpendingChart = lazy(() => import("../components/SpendingChart"));
const labels: Record<VerdictKind, string> = {
  yes: "YES",
  yes_with_conditions: "YES, IF…",
  risky: "RISKY",
  no: "NOT YET",
  insufficient_data: "NEED MORE DATA",
  info: "ANSWER",
};
const tones: Record<VerdictKind, string> = {
  yes: "lime",
  yes_with_conditions: "amber",
  risky: "amber",
  no: "red",
  insufficient_data: "muted",
  info: "muted",
};
const sourceLabel = (s: Source) =>
  ({ live: "LIVE", cached: "CACHED", seeded: "SAMPLE DATA", statement: "YOUR STATEMENT", estimate: "ESTIMATE", error: "FAILED" })[s] ??
  String(s).toUpperCase();
const ordinal = (n: number) => `${n}${n % 10 === 1 && n !== 11 ? "st" : n % 10 === 2 && n !== 12 ? "nd" : n % 10 === 3 && n !== 13 ? "rd" : "th"}`;
const day = (iso?: string | null) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }) : "";
export type Tab = "verdict" | "receipt" | "trace" | "money";
interface Props {
  tab: Tab;
  setTab: (t: Tab) => void;
  verdict: Verdict | null;
  previous: Verdict | null;
  phase: Phase;
  servers: Server[];
  trace: TraceLine[];
  statement: StatementInfo | null;
  today: string;
  onBalance: () => void;
  onHighlight: (s: string) => void;
  error: string;
  onRetry: () => void;
  canAskAgain: boolean;
  onAskAgain: () => void;
  onSetup: () => void;
}
export default function Panels(p: Props) {
  const loading = ["discovering", "calling", "collecting"].includes(p.phase);
  const [drawerOpen, setDrawerOpen] = useState(false);
  useEffect(() => {
    if (p.phase === "done") setDrawerOpen(true);
  }, [p.phase]);
  return (
    <aside
      className={`results card ${drawerOpen ? "drawer-open" : ""}`}
      id="results"
      aria-label="Decision details"
    >
      <button
        className="tablet-drawer-handle"
        aria-expanded={drawerOpen}
        onClick={() => setDrawerOpen(!drawerOpen)}
      >
        {drawerOpen ? "Collapse decision details" : "Open decision details"}
        <span />
      </button>
      <div className="panel-label">
        <Pill>the_full_picture</Pill>
      </div>
      <nav className="tabs" aria-label="Decision details">
        {(["verdict", "receipt", "trace", "money"] as Tab[]).map((t) => (
          <button
            key={t}
            className={p.tab === t ? "active" : ""}
            onClick={() => p.setTab(t)}
            aria-current={p.tab === t ? "page" : undefined}
          >
            {t.toUpperCase()}
            {t === "receipt" && p.verdict && (
              <span>{p.verdict.evidence.length}</span>
            )}
          </button>
        ))}
      </nav>
      <div className="tab-content">
        {p.error && (
          <div className="error-banner">
            <XCircle size={20} />
            <strong>SOURCE DIDN’T RESPOND</strong>
            <p>{p.error}</p>
            <Button onClick={p.onRetry}>Retry</Button>
          </div>
        )}
        {p.tab === "verdict" ? (
          loading ? (
            <div className="result-loading">
              <span className="sticker orange">CHECKING YOUR CONTEXT</span>
              <h2>
                A LITTLE PATIENCE.
                <br />A LOT LESS GUESSWORK.
              </h2>
              <Skeleton />
              <p>Reading only the sources you allow.</p>
            </div>
          ) : p.verdict ? (
            <VerdictView {...p} />
          ) : (
            <EmptyVerdict />
          )
        ) : p.tab === "receipt" ? (
          loading ? (
            <Skeleton />
          ) : (
            <Receipt {...p} />
          )
        ) : p.tab === "trace" ? (
          <Trace lines={p.trace} />
        ) : (
          <Money {...p} />
        )}
      </div>
      <div className="results-footer">
        <ShieldCheck size={16} />
        <span>YOUR DECISION. YOUR DATA. YOUR CALL.</span>
      </div>
    </aside>
  );
}
function EmptyVerdict() {
  return (
    <div className="empty-verdict">
      <div className="empty-icon">
        <ArrowDownRight size={48} />
      </div>
      <Chip tone="muted">NO VERDICT YET</Chip>
      <h2>
        LESS GUESSING.
        <br />
        MORE CONTEXT.
      </h2>
      <p>
        Ask a question. We’ll bring the evidence, the numbers, and the
        trade-offs.
      </p>
      <div className="what-to-expect">
        <span>
          01 <strong>Read allowed sources</strong>
        </span>
        <span>
          02 <strong>Lay out the evidence</strong>
        </span>
        <span>
          03 <strong>Make the call together</strong>
        </span>
      </div>
      <p className="small-note">
        <Info size={15} /> Estimates are labelled. Nothing is booked or
        purchased.
      </p>
    </div>
  );
}
function VerdictView(p: Props) {
  const v = p.verdict!;
  const { reduced } = useMotionPreferences();
  const unknown = v.verdict === "insufficient_data";
  const n = v.numbers;
  const priced = n.trip_cost.low != null && n.trip_cost.high != null;
  const bad = n.remaining.low != null && n.remaining.low < (n.safety_floor ?? 0);
  const costLabel =
    ({ trip: "Trip estimate", purchase: "Item cost", savings_goal: "Item cost", expense: "Outing cost" } as Record<string, string>)[
      v.kind ?? ""
    ] ?? "Estimate";
  return (
    <div className="verdict-view">
      {p.previous && p.previous.question === v.question && p.previous.verdict !== v.verdict && (
        <motion.div
          initial={reduced ? false : { x: 25, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          transition={{ duration: reduced ? 0.15 : 0.24, ease: revealEase }}
          className="previous-verdict"
        >
          <span className="mono">
            {p.previous.evidence.some((e) => e.server === "Finance")
              ? "PREVIOUS ANSWER"
              : "BEFORE FINANCE"}
          </span>
          <strong>{labels[p.previous.verdict]}</strong>
          <small>{p.previous.headline}</small>
        </motion.div>
      )}
      <motion.div
        initial={reduced ? false : { scale: 1.04 }}
        animate={{ scale: 1 }}
        transition={{
          type: "spring",
          duration: reduced ? 0 : 0.24,
          bounce: 0.12,
        }}
        className={`verdict-stamp ${tones[v.verdict]}`}
      >
        {v.verdict === "no" ? (
          <XCircle size={24} />
        ) : unknown || v.verdict === "info" ? (
          <Info size={22} />
        ) : v.verdict === "risky" ? (
          <AlertTriangle size={22} />
        ) : (
          <Check size={24} />
        )}
        <span>{labels[v.verdict]}</span>
      </motion.div>
      <h2 aria-live="polite" className="verdict-headline">
        {v.headline}
      </h2>
      {v.explanation && <p className="verdict-sub">{v.explanation}</p>}
      {unknown && (
        <p className="verdict-sub">
          {p.servers.find((s) => s.id === "finance")?.status !== "connected"
            ? "Finance isn't connected. Add it to see what fits your budget."
            : "A required source or price is missing. The receipt shows what we could read."}
        </p>
      )}
      <div className="confidence">
        <span className="mono">CONFIDENCE: {v.confidence.toUpperCase()}</span>
        <span className="tooltip-wrap" tabIndex={0}>
          <Info size={15} />
          <span role="tooltip">
            How fresh the data behind this answer is: live prices and your statement count as fresh; saved prices and
            estimates make it medium; sample data or a failed source make it low. The numbers themselves come from the
            Orbit engine.
          </span>
        </span>
      </div>
      {v.verdict !== "info" && (
        <div className="numbers">
          <div>
            <span>Balance</span>
            <strong>{n.balance == null ? "Not read" : <AnimatedAmount value={n.balance} />}</strong>
          </div>
          <div>
            <span>{costLabel}</span>
            <strong>
              {priced ? (
                <>
                  <AnimatedAmount value={n.trip_cost.low!} />–
                  <AnimatedAmount value={n.trip_cost.high!} format="number" />
                </>
              ) : (
                "Unavailable"
              )}
            </strong>
          </div>
          <div>
            <span>Monthly commitments</span>
            <strong>
              {n.monthly_commitments != null ? (
                <>
                  ≈ <AnimatedAmount value={n.monthly_commitments} />
                </>
              ) : (
                "Not read"
              )}
            </strong>
          </div>
          <div className={`remaining ${bad ? "negative" : ""}`}>
            <span>Lowest before payday</span>
            <strong>
              {n.remaining.low == null || n.remaining.high == null ? (
                "Not calculated"
              ) : (
                <>
                  <AnimatedAmount value={n.remaining.low} /> to{" "}
                  <AnimatedAmount value={n.remaining.high} />
                </>
              )}
            </strong>
          </div>
          {n.remaining.low != null && n.remaining.high != null && (
            <div
              className="range-chart"
              aria-label={`Lowest point before payday ${money(n.remaining.low)} to ${money(n.remaining.high)}; the middle marker is your ${money(n.safety_floor ?? 0)} safety floor`}
            >
              <span
                className={`range-fill ${bad ? "red" : "amber"}`}
                style={{ left: bad ? "6%" : "42%", width: "44%" }}
              />
              <span className="zero-marker" />
              <small>LOW CASE</small>
              <small>{money(n.safety_floor ?? 0)}</small>
              <small>HIGH CASE</small>
            </div>
          )}
        </div>
      )}
      {n.remaining.low != null && (
        <p className="small-note">
          The engine projects your cash day by day from your statement (salary in, bills and everyday spending out) and
          keeps {money(n.safety_floor ?? 0)} as a safety floor. The line-by-line math is in MONEY.
        </p>
      )}
      {v.tradeoffs.length > 0 && (
        <>
          <div className="section-title">
            <h3>THE PLAN</h3>
            <span className="mono">FROM THE ENGINE</span>
          </div>
          <div className="tradeoffs">
            {v.tradeoffs.map((t, i) => (
              <div key={t} className="option-card">
                <span className="option-number">0{i + 1}</span>
                <span>
                  <strong>{t}</strong>
                </span>
                <ArrowDownRight size={20} />
              </div>
            ))}
          </div>
        </>
      )}
      {p.canAskAgain && (
        <Button tone="violet" className="full-width" onClick={p.onAskAgain}>
          Ask again with Finance
        </Button>
      )}
      <div className="section-title">
        <h3>THE EVIDENCE</h3>
        <span className="mono">{v.evidence.length} READS</span>
      </div>
      <div className="evidence-list">
        {v.evidence.map((e, i) => {
          const Icon = icons[e.server] ?? Eye;
          return (
            <button
              key={`${e.tool}-${i}`}
              className="evidence-row"
              onClick={() => p.onHighlight(e.server)}
            >
              <Icon size={18} />
              <span>
                <strong>{e.finding}</strong>
                <small>
                  <Chip>{sourceLabel(e.source)}</Chip>
                  {e.as_of && <>AS OF {shortDate(e.as_of)}</>}
                </small>
              </span>
            </button>
          );
        })}
      </div>
      <details className="why">
        <summary>Why this answer?</summary>
        <ol>
          <li>We asked each source you switched on which tools it has (tools/list).</li>
          <li>
            We read only those sources. Guardian stops any write the AI asks for: writes happen only when you upload a
            statement.
          </li>
          <li>
            {v.verdict === "info"
              ? "This was a general question, so there was nothing to price."
              : unknown
                ? "Required context is missing, so we cannot calculate a verdict."
                : "The engine projected your cash to the day before your next salary, after this cost and every bill. The steps are in MONEY → THE MATH."}
          </li>
          <li>
            The Python engine owns every number. Gemini, when it answers, only chooses what to read and explains the
            result in words.
          </li>
        </ol>
      </details>
    </div>
  );
}
function Receipt(p: Props) {
  if (!p.verdict)
    return (
      <div className="empty-panel">
        <LockKeyhole size={32} />
        <h2>NOTHING READ YET.</h2>
        <p>Your first answer will come with a receipt.</p>
      </div>
    );
  const today = p.verdict.intent?.today || p.today;
  const stale = p.statement && today && (Date.parse(today) - Date.parse(p.statement.as_of)) / 86400000 > 7;
  const blocked = p.trace.filter((t) => t.status === "denied").length;
  return (
    <div>
      <div className="receipt">
        <div className="receipt-heading">
          <strong>ORBIT</strong>
          <span>CONTEXT RECEIPT</span>
          <small>{today ? shortDate(today).toUpperCase() : ""} · LOCAL</small>
        </div>
        <div className="receipt-columns">
          <div>
            <h3>READ ({p.verdict.evidence.length})</h3>
            {p.verdict.evidence.map((e, i) => (
              <div key={i} className="receipt-entry">
                <strong>{e.server}</strong>
                <span>{e.tool} · 1 read</span>
                <p>{e.finding}</p>
                <small>{e.as_of}</small>
                <Chip>{sourceLabel(e.source)}</Chip>
              </div>
            ))}
          </div>
          <div>
            <h3>NOT READ</h3>
            {p.verdict.not_read.map((s) => (
              <div className="receipt-entry unread" key={s}>
                <LockKeyhole size={14} />
                <p>{s}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="receipt-total">
          <span>WRITE TOOLS EXECUTED</span>
          <strong>0</strong>
        </div>
        {blocked > 0 && (
          <div className="receipt-total">
            <span>WRITES BLOCKED BY GUARDIAN</span>
            <strong>{blocked}</strong>
          </div>
        )}
        <div className="barcode" aria-hidden="true" />
        <p className="receipt-end">YOUR CONTEXT BELONGS TO YOU.</p>
      </div>
      {stale && p.statement && (
        <div className="warning-card">
          <AlertTriangle size={20} />
          <div>
            <strong>Your balance is over 7 days old.</strong>
            <p>
              It’s from {shortDate(p.statement.as_of)}. Upload a newer statement before relying on an estimate.
            </p>
            <Button onClick={p.onBalance}>Update balance</Button>
          </div>
        </div>
      )}
    </div>
  );
}
function Trace({ lines }: { lines: TraceLine[] }) {
  const [paused, setPaused] = useState(false);
  const [copied, setCopied] = useState(false);
  const scroll = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!paused && scroll.current)
      scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [lines, paused]);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(
        lines
          .map((l) => `${l.ts} > ${l.tool} ${l.server} ${l.ms}ms ${l.status}`)
          .join("\n"),
      );
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div>
      <TerminalCard filename="mcp_trace.log" tag="LIVE">
        <div className="trace-toolbar">
          <Button onClick={() => setPaused(!paused)}>
            {paused ? <Play size={15} /> : <Pause size={15} />}{" "}
            {paused ? "Resume" : "Pause"}
          </Button>
          <Button onClick={copy}>
            <Copy size={15} />
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
        <div
          className="trace-scroll"
          ref={scroll}
          aria-live={paused ? "off" : "polite"}
        >
          {lines.length ? (
            lines.map((l, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className={`trace-line ${l.status}`}
              >
                <span className="trace-time">{l.ts.slice(11, 19)}</span>
                <p>
                  &gt; {l.tool} {l.server.toLowerCase()}
                  <br />
                  <span>
                    {l.ms}ms · {l.status}
                  </span>
                </p>
              </motion.div>
            ))
          ) : (
            <p className="terminal-empty">
              &gt; Ready. Ask a question to start.
              <br />
              &gt; No tools called.
            </p>
          )}
        </div>
        <div className="terminal-summary">0 WRITE TOOLS EXECUTED</div>
      </TerminalCard>
      <p className="small-note">
        Every MCP call Orbit made for this answer, as the backend recorded it: when, which server and tool, how long it
        took, and who chose it (Gemini or the rules planner).
      </p>
    </div>
  );
}
function Money(p: Props) {
  const n = p.verdict?.numbers;
  const s = p.statement?.summary;
  const bt = s?.forecast.backtest;
  return (
    <div className="money-view">
      <Chip tone="amber">{p.statement ? "FROM YOUR STATEMENT" : "NO STATEMENT YET"}</Chip>
      <h2>THE MATH, LINE BY LINE.</h2>
      <p>How the lowest point before payday was worked out. Every line comes from the Orbit engine.</p>
      {n?.math?.length ? (
        <div className="cost-table" aria-label="The math">
          <div className="cost-head">
            <span>LINE</span>
            <span />
            <span>RS</span>
          </div>
          {n.math.map((row, i) => (
            <div className="cost-row" key={i}>
              <span>
                {i === n.math!.length - 1 ? "= " : row.amount < 0 ? "− " : "+ "}
                {row.label}
              </span>
              <span />
              <span>{money(i === n.math!.length - 1 ? row.amount : Math.abs(row.amount))}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="small-note">Ask about a trip, a purchase or a night out with your budget connected to see the math.</p>
      )}
      {n?.cash_on_day != null && (
        <div className="commitments-card">
          <Wallet size={23} />
          <div>
            <strong>
              <AnimatedAmount value={n.cash_on_day} />
            </strong>
            <p>Cash on {day(n.pay_day)}, before paying (estimated)</p>
            {n.remaining.low != null && n.remaining.high != null && (
              <small>
                Lowest before payday ({day(n.next_salary)}): {money(n.remaining.low)} to {money(n.remaining.high)}.
                Safety floor {money(n.safety_floor ?? 0)}.
              </small>
            )}
          </div>
        </div>
      )}
      <div className="section-title">
        <h3>MONTHLY SPENDING</h3>
        <strong>{s ? <>≈ <AnimatedAmount value={s.monthly_avg_spend} /></> : "Not read"}</strong>
      </div>
      <Suspense fallback={<Skeleton />}>
        <SpendingChart categories={s?.monthly_avg_by_category || {}} />
      </Suspense>
      <Button onClick={p.onSetup} className="full-width">
        Import a statement
      </Button>
      {s && (
        <div className="commitments-card">
          <Wallet size={23} />
          <div>
            <strong>
              ≈ <AnimatedAmount value={s.monthly_commitments} /> / month
            </strong>
            <p>Rent, bills and SIPs from your statement</p>
            <small>
              {s.recurring
                .filter((r) => r.type === "debit")
                .map((r) => `${r.category} ${money(r.amount)} on the ${ordinal(r.day_of_month)}`)
                .join(" · ") || "No recurring bills found."}
            </small>
          </div>
        </div>
      )}
      {s && (
        <div className="commitments-card">
          <Info size={23} />
          <div>
            <strong>The forecast</strong>
            <p>
              Everyday spending: {s.forecast.method}. Learned from {s.forecast.trained_on.days} days of your statement.
            </p>
            <small>
              {bt
                ? `Back-tested on your last ${bt.days} days: the weekday pattern was off by ~${money(bt.weekday_miss_per_3_days)} per 3 days, a flat daily average by ~${money(bt.flat_miss_per_3_days)}. Using the ${bt.chosen === "weekday" ? "weekday pattern" : "flat average"}.`
                : "Not enough history to back-test yet, so the forecast uses your daily average."}
            </small>
          </div>
        </div>
      )}
      <div className="privacy-note">
        <ShieldCheck size={17} />
        <p>
          No bank connection. Your statement was masked on upload: only dates, categories, amounts and the balance were
          kept.
        </p>
      </div>
    </div>
  );
}
