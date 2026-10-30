import { lazy, Suspense, useState, type DragEvent } from "react";
import { Upload, Check, Wallet, PlugZap, AlertTriangle, ShieldCheck } from "lucide-react";
import type { Server, StatementInfo } from "../types";
import { api } from "../api";
import {
  Button,
  Chip,
  Modal,
  Pill,
  AnimatedAmount,
  shortDate,
  Skeleton,
} from "../components/ui";
const SpendingChart = lazy(() => import("../components/SpendingChart"));
export function SetupDialog({
  onClose,
  onDone,
  statement,
  financeOn,
  onFinanceOn,
  balanceOnly = false,
}: {
  onClose: () => void;
  onDone: (s: StatementInfo) => void;
  statement: StatementInfo | null;
  financeOn: boolean;
  onFinanceOn: () => Promise<void>;
  balanceOnly?: boolean;
}) {
  const [step, setStep] = useState(balanceOnly && statement ? 2 : 1);
  const [preview, setPreview] = useState<StatementInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const shown = preview || statement;
  // Choosing a file IS the upload: the backend masks it in memory and hands only the kept columns to Finance.
  const load = async (input: File) => {
    setLoading(true);
    setError("");
    try {
      const info = await api.uploadStatement(input);
      setPreview(info);
      onDone(info);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };
  const drop = (e: DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) void load(file);
  };
  if (!financeOn)
    return (
      <Modal title="A LITTLE CONTEXT FIRST." onClose={onClose} label="your_setup">
        <p>Your budget source is off. Turn it on to add a statement and see your balance.</p>
        <div className="approval-note">
          <ShieldCheck size={19} />
          <span>Orbit only reads what you upload. It never connects to your bank.</span>
        </div>
        {error && (
          <p role="alert" className="field-error">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <Button
            tone="lime"
            disabled={loading}
            onClick={async () => {
              setLoading(true);
              setError("");
              try {
                await onFinanceOn();
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setLoading(false);
              }
            }}
          >
            {loading ? "Turning on…" : "Turn on Budget"}
          </Button>
        </div>
      </Modal>
    );
  return (
    <Modal
      title={step === 1 ? "A LITTLE CONTEXT FIRST." : "WHAT’S YOUR BALANCE?"}
      onClose={onClose}
      label="your_setup"
    >
      <div className="setup-steps">
        <span className={step === 1 ? "current" : "complete"}>
          01 / STATEMENT
        </span>
        <span className={step === 2 ? "current" : ""}>02 / BALANCE</span>
      </div>
      {step === 1 ? (
        <>
          <p>Add your statement. Keep the decision grounded.</p>
          <div
            className="dropzone"
            onDragOver={(e) => e.preventDefault()}
            onDrop={drop}
          >
            <Upload size={32} />
            <strong>Drop a CSV here</strong>
            <span>or choose it from your device</span>
            <input
              aria-label="Choose a statement CSV"
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) void load(file);
              }}
            />
          </div>
          <details className="advanced-connection">
            <summary>About the file format</summary>
            <p>
              A bank statement CSV with a date, a narration or category, debit, credit and balance columns. Orbit keeps
              only the date, category, amounts and balance; narrations (names, UPI IDs, account numbers) never leave the
              upload.
            </p>
          </details>
          {loading ? (
            <>
              <Pill>masking_statement</Pill>
              <Skeleton />
            </>
          ) : preview ? (
            <div className="statement-preview">
              <Chip tone="lime">
                <Check size={15} /> STATEMENT READY
              </Chip>
              <strong>
                {preview.receipt ? (
                  <>
                    <AnimatedAmount value={preview.receipt.rows_kept} format="number" /> transactions
                  </>
                ) : (
                  "Your statement"
                )}
              </strong>
              <p>
                {preview.receipt && (
                  <>
                    {shortDate(preview.receipt.from)} to {shortDate(preview.receipt.to)}
                    <br />
                  </>
                )}
                Average spend ≈ <AnimatedAmount value={preview.summary.monthly_avg_spend} />
                /month
              </p>
              <Suspense fallback={<Skeleton />}>
                <SpendingChart categories={preview.summary.monthly_avg_by_category} />
              </Suspense>
              {preview.receipt && (
                <small>
                  Kept only {preview.receipt.kept_columns.join(", ")}. Left out{" "}
                  {preview.receipt.dropped_columns.join(", ") || "nothing"}.
                </small>
              )}
            </div>
          ) : null}
          {error && (
            <div className="error-banner">
              <span className="sticker red">COULDN’T READ THIS FILE</span>
              <p>{error}</p>
            </div>
          )}
          <div style={{display:"flex", justifyContent:"flex-end", }} className="modal-actions">
            <Button
              tone="lime"
              disabled={!shown || loading}
              onClick={() => setStep(2)}
            >
              Continue
            </Button>
          </div>
        </>
      ) : (
        <>
          <p>We never connect to your bank. This is the running balance on your statement’s last row.</p>
          <div className="balance-field" aria-label="Balance from your statement">
            <span>Rs</span>
            <strong>
              {shown ? <AnimatedAmount value={shown.balance} format="number" /> : "—"}
            </strong>
          </div>
          {shown && <p className="date-field">AS OF {shortDate(shown.as_of)}</p>}
          <div className="approval-note">
            <Wallet size={19} />
            <span>
              To change it, upload a newer statement. Orbit never edits your balance or your bank account.
            </span>
          </div>
          <div className="modal-actions">
            <Button onClick={() => setStep(1)}>{balanceOnly ? "Upload a newer statement" : "Go back"}</Button>
            <Button tone="lime" onClick={onClose}>
              Done
            </Button>
          </div>
        </>
      )}
    </Modal>
  );
}
export function ConnectDialog({
  onClose,
  onConnected,
}: {
  onClose: () => void;
  onConnected: (servers: Server[]) => void;
}) {
  const [stage, setStage] = useState(0);
  const [server, setServer] = useState<Server | null>(null);
  const [error, setError] = useState("");
  const connect = async () => {
    setError("");
    setStage(1);
    try {
      const { servers } = await api.setSource("finance", true); // the hot-plug: Finance's tools/list, for real
      setStage(2);
      const finance = servers.find((s) => s.id === "finance");
      if (!finance || finance.status !== "connected")
        throw Error("The budget source didn’t answer. Is run_servers.py running?");
      setStage(3);
      setServer(finance);
      onConnected(servers);
    } catch (e) {
      setStage(0);
      setError((e as Error).message);
    }
  };
  return (
    <Modal title="ADD YOUR BUDGET." onClose={onClose} label="your_budget">
      <p>
        Connect your budget to check what fits. It reads your uploaded statement; we never connect to your bank.
      </p>
      {stage === 0 ? (
        <Button tone="lime" onClick={() => void connect()}>
          <PlugZap size={18} />
          Connect budget
        </Button>
      ) : (
        <ol className="connect-steps">
          {[
            "Connecting your budget",
            "Checking available information",
            "Ready to use",
          ].map((s, i) => (
            <li key={s} className={stage > i ? "complete" : ""}>
              <span>{stage > i ? <Check size={17} /> : i + 1}</span>
              {s}
            </li>
          ))}
        </ol>
      )}
      {error && (
        <p role="alert" className="field-error">
          {error}
        </p>
      )}
      {server && (
        <>
          <div className="budget-read-summary">
            <strong>Orbit can now read:</strong>
            <ul>
              <li>The balance on your uploaded statement</li>
              <li>Your spending, bills and SIPs from that statement</li>
              <li>Your cost estimates</li>
            </ul>
          </div>
          <details className="advanced-connection">
            <summary>See the {server.tools.length} discovered tools</summary>{" "}
            <div className="discovered-tools">
              {server.tools.map((t) => (
                <div key={t.name}>
                  <code>{t.name}</code>
                  <Chip tone={t.kind === "write" ? "amber" : "muted"}>
                    {t.kind.toUpperCase()}
                  </Chip>
                  <p>{t.description}</p>
                </div>
              ))}
            </div>
          </details>
          <div className="approval-note">
            <AlertTriangle size={18} />
            <span>
              Reading only. The one write tool (loading a statement) runs only when you upload one; the AI can’t call it.
            </span>
          </div>
          <Button tone="lime" className="full-width" onClick={onClose}>
            Done
          </Button>
        </>
      )}
    </Modal>
  );
}
