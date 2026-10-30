import { memo, useMemo, useState, useEffect } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Handle,
  Position,
  BaseEdge,
  getSmoothStepPath,
  type EdgeProps,
  type NodeProps,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Check,
  LockKeyhole,
  Eye,
  ArrowDownRight,
  RotateCcw,
} from "lucide-react";
import { motion } from "framer-motion";
import type { Server, Verdict, Phase } from "../types";
import { Button, icons, Pill } from "./ui";
import {
  revealEase,
  useMotionPreferences,
} from "../hooks/useMotionPreferences";
type GraphData = {
  label: string;
  caption: string;
  kind: "question" | "source" | "verdict";
  state: string;
  source?: string;
  selected?: boolean;
  pulse?: number;
};
type GraphNode = Node<GraphData>;
function GraphRipple({ pulse }: { pulse?: number }) {
  if (!pulse) return null;
  return (
    <span className="graph-ripples" key={pulse} aria-hidden="true">
      {[0, 1].map((ring) => (
        <motion.span
          key={ring}
          className="graph-ripple"
          initial={{ opacity: 0.65, scale: 0.98 }}
          animate={{ opacity: 0, scale: 1.1 }}
          transition={{ duration: 0.85, delay: ring * 0.16, ease: revealEase }}
        />
      ))}
    </span>
  );
}
const ContextNode = memo(function ContextNode({ data }: NodeProps<GraphNode>) {
  const { reduced } = useMotionPreferences();
  const Icon = icons[data.label] || Eye;
  const done = data.state === "returned";
  return (
    <motion.div
      initial={reduced ? false : { scale: 0.98, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ duration: 0.24, ease: revealEase }}
      className={`graph-node ${data.kind} ${data.state} ${data.selected ? "highlighted" : ""}`}
    >
      {!reduced && <GraphRipple pulse={data.pulse} />}
      <Handle type="target" position={Position.Top} />
      <div className="node-top">
        {data.kind === "source" ? (
          <Icon size={19} />
        ) : data.kind === "question" ? (
          <Eye size={19} />
        ) : (
          <ArrowDownRight size={20} />
        )}
        <strong>{data.label}</strong>
        {done ? (
          <Check size={16} />
        ) : data.state === "skipped" ? (
          <LockKeyhole size={15} />
        ) : null}
      </div>
      <div className="node-caption">{data.caption}</div>
      {data.source && (
        <div className="node-provenance">{data.source.toUpperCase()}</div>
      )}
      <Handle type="source" position={Position.Bottom} />
    </motion.div>
  );
});
const nodeTypes = { context: ContextNode };
const FlowEdge = memo(function FlowEdge(props: EdgeProps) {
  const { reduced } = useMotionPreferences();
  const [path] = getSmoothStepPath(props);
  const enabled = Boolean(props.data?.enabled);
  const collecting = Boolean(props.data?.collecting);
  const signal = Number(props.data?.signal || 0);
  return (
    <>
      <BaseEdge
        path={path}
        style={{
          stroke: enabled ? "var(--forest-600)" : "var(--hairline)",
          strokeWidth: enabled ? 2.5 : 1.5,
          strokeDasharray: enabled ? undefined : "5 5",
        }}
      />
      {enabled && !reduced && (
        <motion.path
          d={path}
          fill="none"
          stroke="var(--orange)"
          strokeWidth={2.5}
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.3 }}
        />
      )}
      {(collecting || signal > 0) && !reduced && (
        <motion.g
          key={`${signal}-${collecting}`}
          initial={{ opacity: 0 }}
          animate={{ opacity: [0, 1, 1, 0] }}
          transition={{ duration: 0.65, times: [0, 0.1, 0.85, 1] }}
        >
          <circle
            r="4"
            fill="var(--mint-300)"
            stroke="var(--ink)"
            strokeWidth="1.5"
          >
            <animateMotion
              dur="0.65s"
              path={path}
              repeatCount="1"
              fill="freeze"
            />
          </circle>
        </motion.g>
      )}
    </>
  );
});
const edgeTypes = { flow: FlowEdge };
export default function EvidenceGraph({
  servers,
  phase,
  active,
  returned,
  verdict,
  question,
  highlight,
  skip,
  slow,
}: {
  servers: Server[];
  phase: Phase;
  active: string[];
  returned: string[];
  verdict: Verdict | null;
  question: string;
  highlight: string;
  skip: () => void;
  slow: boolean;
}) {
  const { reduced } = useMotionPreferences();
  const [replayCycle, setReplayCycle] = useState(0);
  // This replays existing evidence visually. It never calls a tool or changes a result.
  const [presentation, setPresentation] = useState({ run: 0, step: 0 });
  useEffect(() => {
    if (phase !== "done" || reduced) {
      setPresentation((p) => ({ ...p, step: 0 }));
      return;
    }
    setPresentation((p) => ({ run: p.run + 1, step: 1 }));
    const timers = [
      setTimeout(() => setPresentation((p) => ({ ...p, step: 2 })), 450),
      setTimeout(() => setPresentation((p) => ({ ...p, step: 3 })), 1200),
      setTimeout(() => setPresentation((p) => ({ ...p, step: 4 })), 2300),
    ];
    return () => timers.forEach(clearTimeout);
  }, [phase, verdict, reduced, replayCycle]);
  const replaying = presentation.step > 0 && presentation.step < 4;
  const pulseFor = (kind: GraphData["kind"], state: string) => {
    if (reduced) return 0;
    if (phase === "done") {
      const step = kind === "question" ? 1 : kind === "source" ? 2 : 3;
      return presentation.step >= step && state !== "skipped"
        ? presentation.run + 100
        : 0;
    }
    if (kind !== "source") return 0;
    return state === "calling" ? 1 : state === "returned" ? 2 : 0;
  };
  const [wide, setWide] = useState(
    () =>
      typeof window === "undefined" ||
      window.matchMedia("(min-width: 768px)").matches,
  );
  useEffect(() => {
    const media = window.matchMedia("(min-width: 768px)");
    const update = () => setWide(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const nodes = useMemo<GraphNode[]>(() => {
    const completed = phase === "collecting" || phase === "done";
    const list: GraphNode[] = [
      {
        id: "question",
        type: "context",
        position: { x: 165, y: 25 },
        data: {
          label: "YOUR QUESTION",
          caption: phase === "idle" ? "A decision starts here." : question,
          kind: "question",
          state: phase === "idle" ? "idle" : "active",
          pulse: pulseFor("question", "active"),
        },
      },
    ];
    servers.forEach((s, i) => {
      const ev = verdict?.evidence.find((e) => e.server === s.name);
      const read = active.includes(s.id);
      const idle = phase === "idle";
      const state = returned.includes(s.id)
        ? "returned"
        : idle
          ? s.status === "connected"
            ? "idle"
            : "skipped"
          : completed
            ? ev
              ? "returned"
              : "skipped"
            : read
              ? "calling"
              : "skipped";
      list.push({
        id: s.id,
        type: "context",
        position: { x: 18 + (i % 3) * 176, y: 170 + Math.floor(i / 3) * 165 },
        data: {
          label: s.name,
          caption: idle
            ? s.status === "off"
              ? "Not connected"
              : `${s.tools.length} tools · ${s.permission === "allow" ? "read allowed" : "switched off"}`
            : completed || returned.includes(s.id)
              ? ev?.finding ||
                `Skipped: ${s.status === "off" ? "not connected" : s.permission === "off" ? "permission off" : "not needed"}`
              : read
                ? `${s.name.toLowerCase()}.${s.tools.find((t) => t.kind === "read")?.name}`
                : "Skipped: permission off",
          kind: "source",
          state,
          source: completed || returned.includes(s.id) ? ev?.source : undefined,
          selected: highlight === s.name,
          pulse: pulseFor("source", state),
        },
      });
    });
    list.push({
      id: "verdict",
      type: "context",
      position: { x: 165, y: 520 },
      data: {
        label: phase === "done" ? "YOUR VERDICT" : "THE WHOLE PICTURE",
        caption:
          phase === "done"
            ? verdict?.headline || ""
            : "Evidence in. A better call out.",
        kind: "verdict",
        state:
          phase === "done"
            ? verdict?.verdict === "no"
              ? "blocked"
              : "returned"
            : "idle",
        pulse: pulseFor("verdict", "returned"),
      },
    });
    return list;
  }, [
    servers,
    phase,
    active,
    returned,
    verdict,
    question,
    highlight,
    presentation,
    reduced,
  ]);
  const edges = useMemo<Edge[]>(
    () =>
      servers.flatMap((s) => [
        {
          id: `q-${s.id}`,
          source: "question",
          target: s.id,
          type: "flow",
          data: {
            enabled: active.includes(s.id),
            collecting: false,
            signal:
              active.includes(s.id) && presentation.step >= 1
                ? presentation.run
                : 0,
          },
          animated: false,
          className: active.includes(s.id) ? "edge-active" : "edge-muted",
        },
        {
          id: `v-${s.id}`,
          source: s.id,
          target: "verdict",
          type: "flow",
          data: {
            enabled:
              active.includes(s.id) &&
              (phase === "collecting" || phase === "done"),
            collecting: active.includes(s.id) && phase === "collecting",
            signal:
              active.includes(s.id) && presentation.step >= 2
                ? presentation.run
                : 0,
          },
          animated: false,
          className:
            phase === "collecting" || phase === "done"
              ? "edge-returned"
              : "edge-muted",
        },
      ]),
    [servers, active, phase, presentation],
  );
  return (
    <section className="graph-panel card" aria-label="Evidence flow">
      <div className="panel-label">
        <Pill>show_the_work</Pill>
        <span className="mono graph-status">
          <span
            className={`status-dot ${phase === "calling" ? "calling" : "connected"}`}
          />
          {phase === "idle"
            ? "WAITING FOR A QUESTION"
            : phase === "done"
              ? "CONTEXT COLLECTED"
              : phase === "error"
                ? "SOURCE ERROR"
                : "READING CONTEXT"}
        </span>
      </div>
      <div className="graph-title">
        <h2>NOT A BLACK BOX.</h2>
        <p>Watch your context become a decision.</p>
      </div>
      <div
        className="graph-canvas"
        role="img"
        aria-label="Question flows to permissioned sources, then into your verdict"
      >
        {wide && (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            fitViewOptions={{ padding: 0.1 }}
            minZoom={0.5}
            maxZoom={1.1}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            panOnDrag={false}
            zoomOnScroll={false}
            zoomOnDoubleClick={false}
            preventScrolling={false}
            proOptions={{ hideAttribution: true }}
          >
            <Background
              variant={BackgroundVariant.Lines}
              gap={40}
              color="var(--grid-line)"
            />
          </ReactFlow>
        )}
      </div>
      <div className="mobile-flow">
        <div className="mobile-flow-question">
          {!reduced && <GraphRipple pulse={pulseFor("question", "active")} />}
          <Eye size={18} />
          <strong>YOUR QUESTION</strong>
          <p>{phase === "idle" ? "A decision starts here." : question}</p>
        </div>
        <div className="mobile-flow-sources">
          {servers.map((s) => {
            const Icon = icons[s.name];
            const e = verdict?.evidence.find((e) => e.server === s.name);
            return (
              <div
                key={s.id}
                className={`mobile-flow-source ${returned.includes(s.id) ? "returned" : active.includes(s.id) ? "calling" : ""}`}
              >
                {!reduced && (
                  <GraphRipple
                    pulse={pulseFor(
                      "source",
                      returned.includes(s.id)
                        ? "returned"
                        : active.includes(s.id)
                          ? "calling"
                          : "skipped",
                    )}
                  />
                )}
                <Icon size={19} />
                <span>
                  <strong>{s.name}</strong>
                  <small>
                    {e && returned.includes(s.id)
                      ? e.finding
                      : s.status === "off"
                        ? "Skipped: not connected"
                        : s.permission === "off"
                          ? "Skipped: permission off"
                          : active.includes(s.id)
                            ? "Reading context…"
                            : "Read allowed"}
                  </small>
                </span>
                {s.status === "off" || s.permission === "off" ? (
                  <LockKeyhole size={16} />
                ) : returned.includes(s.id) ? (
                  <Check size={16} />
                ) : null}
              </div>
            );
          })}
        </div>
        <div className="mobile-flow-verdict">
          {!reduced && <GraphRipple pulse={pulseFor("verdict", "returned")} />}
          <strong>
            {phase === "done"
              ? verdict?.headline
              : "Evidence in. A better call out."}
          </strong>
        </div>
      </div>
      <footer className="graph-footer">
        <span>
          <i className="line-key" />
          Permissioned context flow
        </span>
        {phase !== "idle" && phase !== "done" && phase !== "error" ? (
          <Button className="compact" onClick={skip}>
            Skip animation
          </Button>
        ) : phase === "done" && !reduced ? (
          <Button
            className="compact"
            onClick={() => setReplayCycle((n) => n + 1)}
            disabled={replaying}
          >
            <RotateCcw size={14} aria-hidden="true" />
            Replay flow
          </Button>
        ) : (
          <span className="mono">
            {slow ? "SLOW ×2" : "TOOLS → EVIDENCE → VERDICT"}
          </span>
        )}
      </footer>
      {phase === "done" && !reduced && (
        <p className="graph-motion-note">
          Animation of existing evidence. No new reads.
        </p>
      )}
      <details className="graph-alternative">
        <summary>Read the evidence flow as text</summary>
        <ol>
          <li>Your question: {question || "Waiting for a question"}</li>
          {servers.map((s) => (
            <li key={s.id}>
              {s.name}:{" "}
              {verdict?.evidence
                .filter((e) => e.server === s.name)
                .map((e) => e.finding)
                .join("; ") || `${s.status}, permission ${s.permission}`}
            </li>
          ))}
          <li>{verdict?.headline || "No answer yet"}</li>
        </ol>
      </details>
    </section>
  );
}
