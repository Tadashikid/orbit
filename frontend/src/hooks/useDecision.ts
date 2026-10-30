import { useCallback, useEffect, useRef, useState } from "react";
import { useReducedMotion } from "framer-motion";
import { api, presentVerdict } from "../api";
import type { Approval, Phase, Server, TraceLine, Verdict, DecisionResult } from "../types";
export function useDecision() {
  const reduced = useReducedMotion();
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [previous, setPrevious] = useState<Verdict | null>(null);
  const [pending, setPending] = useState<Verdict | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [active, setActive] = useState<string[]>([]);
  const [returned, setReturned] = useState<string[]>([]);
  const [trace, setTrace] = useState<TraceLine[]>([]);
  const [error, setError] = useState("");
  const [step, setStep] = useState(""); // the agent's latest step, live while it works
  const [approvals, setApprovals] = useState<Approval[]>([]); // holds waiting for you
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const token = useRef(0);
  const last = useRef<DecisionResult | null>(null);
  const finishRef = useRef<(() => void) | null>(null);
  const clear = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };
  useEffect(
    () => () => {
      clear();
      token.current++;
    },
    [],
  );
  const run = useCallback(
    async (question: string, servers: Server[], slow = false, quick = false) => {
      clear();
      const id = ++token.current;
      setError("");
      setPhase("discovering");
      setActive([]);
      setReturned([]);
      setTrace([]);
      setStep("");
      setPrevious(verdict);
      try {
        const result = await api.decide(question, servers, (s) => {
          if (token.current === id) setStep(s);
        });
        if (token.current !== id) return;
        last.current = result;
        const next = presentVerdict(result);
        setPending(next);
        const finish = () => {
          if (token.current !== id) return;
          clear();
          setTrace(result.trace);
          // Evidence from a server the registry doesn't list (or a failed one) lights no source.
          const read = [
            ...new Set(
              next.evidence
                .filter((e) => e.source !== "error")
                .map((e) => servers.find((s) => s.name === e.server)?.id)
                .filter((id): id is string => Boolean(id)),
            ),
          ];
          setActive(read);
          setReturned(read);
          setVerdict(next);
          setApprovals(result.approvals);
          setPending(null);
          setPhase("done");
        };
        finishRef.current = finish;
        if (reduced || quick) {
          timers.current.push(setTimeout(finish, quick ? 350 : 150));
          return;
        }
        const factor = slow ? 2 : 1;
        const schedule = (ms: number, fn: () => void) => {
          timers.current.push(
            setTimeout(() => {
              if (token.current === id) fn();
            }, ms * factor),
          );
        };
        schedule(200, () =>
          setTrace(result.trace.filter((t) => t.tool.startsWith("tools/list"))),
        );
        const readServers = servers.filter((s) =>
          next.evidence.some((e) => e.server === s.name && e.source !== "error"),
        );
        readServers.forEach((s, i) => {
          schedule(250 + i * 250, () => {
            setPhase("calling");
            setActive((a) => [...a, s.id]);
          });
          schedule(850 + i * 250, () => {
            setReturned((a) => [...a, s.id]);
            setTrace((t) => [
              ...t,
              ...result.trace.filter(
                (l) => l.server === s.name && l.tool.startsWith("tools/call"),
              ),
            ]);
          });
        });
        schedule(1800, () => {
          setPhase("collecting");
          setTrace(result.trace);
        });
        schedule(3300, finish);
      } catch (e) {
        if (token.current === id) {
          setError((e as Error).message);
          setPhase("error");
        }
      }
    },
    [verdict, reduced],
  );
  const reset = () => {
    clear();
    token.current++;
    finishRef.current = null;
    last.current = null;
    api.newConversation();
    setStep("");
    setApprovals([]);
    setVerdict(null);
    setPrevious(null);
    setPending(null);
    setTrace([]);
    setError("");
    setPhase("idle");
    setActive([]);
    setReturned([]);
  };
  return {
    verdict,
    previous,
    pending,
    phase,
    active,
    returned,
    trace,
    error,
    step,
    approvals,
    // an approval card's new state, from the server (confirmed, declined, expired)
    updateApproval: (a: Approval) => setApprovals((all) => all.map((x) => (x.id === a.id ? a : x))),
    run,
    reset,
    skip: () => finishRef.current?.(),
    appendTrace: (line: TraceLine) => setTrace((t) => [...t, line]),
  };
}
