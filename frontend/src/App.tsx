import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Eye,
  CalendarCheck,
  Info,
  LogOut,
  Mic,
  MessageCircle,
  SlidersHorizontal,
  Square,
  Ticket,
  Wallet,
  ShieldCheck,
  Check,
  WifiOff,
  X,
  RefreshCw,
} from "lucide-react";
import SourceDock from "./components/SourceDock";
import Approvals from "./components/Approvals";
import { Atmosphere, ContextConnections } from "./components/Atmosphere";
import { useSurfaceMotion } from "./hooks/useSurfaceMotion";
import { revealEase, useMotionPreferences } from "./hooks/useMotionPreferences";
import PlanJourney from "./screens/PlanJourney";
const EvidenceGraph = lazy(() => import("./components/EvidenceGraph"));
import type { Tab } from "./screens/Panels";
const Panels = lazy(() => import("./screens/Panels"));
import { ConnectDialog, SetupDialog } from "./screens/Dialogs";
import { Skeleton, Button, Chip, Modal, AnimatedAmount } from "./components/ui";
import { api, type GoogleStatus } from "./api";
import { useDecision } from "./hooks/useDecision";
import { Voice, voiceSummary, type VoiceEvent } from "./voice";
import { WakeWord, wakeSupported } from "./wake";
import type { Approval, Server, StatementInfo } from "./types";
export const HERO = "Can I afford a Goa trip next weekend?";
const prompts = [
  { q: HERO, label: "A Goa weekend" },
  { q: "Can I buy a table?", label: "A new table" },
  { q: "Can I go to a fancy dinner this Saturday with 3 friends?", label: "Dinner out" },
];
// The engine's own words when it ignored instructions hidden in an email (backend/engine.py INJECTION).
const INJECTED = /instructions aimed at the AI/i;
interface Nudge {
  id: number;
  message: string;
  action: () => void;
  label: string;
}
function NudgeToast({ n, onDismiss }: { n: Nudge; onDismiss: () => void }) {
  const { reduced } = useMotionPreferences();
  const [paused, setPaused] = useState(false);
  const [remaining, setRemaining] = useState(6000);
  useEffect(() => {
    if (paused) return;
    const t = setInterval(() => setRemaining((r) => Math.max(0, r - 100)), 100);
    return () => clearInterval(t);
  }, [paused]);
  useEffect(() => {
    if (remaining === 0) onDismiss();
  }, [remaining, onDismiss]);
  return (
    <motion.div
      className="nudge card"
      initial={reduced ? false : { y: -12, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: reduced ? 0.15 : 0.24, ease: revealEase }}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <div>
        <Chip tone="lime">CONTEXT CHANGED</Chip>
        <Button
          className="icon-button"
          aria-label="Dismiss notification"
          onClick={onDismiss}
        >
          <X size={16} />
        </Button>
      </div>
      <strong>{n.message}</strong>
      <Button
        onClick={() => {
          n.action();
          onDismiss();
        }}
      >
        {n.label}
      </Button>
      <div
        className="nudge-progress"
        style={{ transform: `scaleX(${remaining / 6000})` }}
      />
    </motion.div>
  );
}
export default function App({ onSignOut }: { onSignOut?: () => void }) {
  const { reduced } = useSurfaceMotion();
  const d = useDecision();
  const [servers, setServers] = useState<Server[]>([]);
  const [today, setToday] = useState("");
  const [live, setLive] = useState<boolean | null>(null); // null = connecting
  const [apiError, setApiError] = useState("");
  const [statement, setStatement] = useState<StatementInfo | null>(null);
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState(HERO);
  const [tab, setTab] = useState<Tab>("verdict");
  const [setup, setSetup] = useState(false);
  // Your own Google Calendar + Gmail, for the emails and events you approve. Google sends you back with ?google=...
  const [google, setGoogle] = useState<GoogleStatus | null>(null);
  const [googleNote, setGoogleNote] = useState(() => {
    const back = new URLSearchParams(globalThis.location?.search).get("google"); // no location in the DOM tests
    if (back) history.replaceState(null, "", location.pathname);
    return back === "connected"
      ? "Google connected: Orbit can now send the emails and add the events you approve."
      : back === "cancelled"
        ? "Google wasn't connected: you cancelled on Google's page."
        : back
          ? "Google couldn't be connected. Try again."
          : "";
  });
  useEffect(() => {
    api.googleStatus().then(setGoogle, () => undefined);
  }, []);
  const toggleGoogle = async () => {
    if (!google?.connected) return void location.assign("/api/google/connect");
    if (!confirm(`Disconnect ${google.email}? Orbit won't be able to send email or add events until you connect again.`)) return;
    setGoogle(await api.disconnectGoogle());
    setGoogleNote("Google disconnected. Orbit no longer has access.");
  };
  const [balanceOnly, setBalanceOnly] = useState(false);
  const [connect, setConnect] = useState(false);
  const [demo, setDemo] = useState(false);
  const [insights, setInsights] = useState(false);
  const [slow, setSlow] = useState(false);
  const [highlight, setHighlight] = useState("");
  const [nudges, setNudges] = useState<Nudge[]>([]);
  const [askError, setAskError] = useState("");
  const [justConnected, setJustConnected] = useState(false);
  const [dismissed, setDismissed] = useState<object | null>(null);
  const busy = ["discovering", "calling", "collecting"].includes(d.phase);
  const financeOn = servers.some((s) => s.id === "finance" && s.status === "connected");
  const loadStatement = useCallback(async (on: boolean) => {
    setStatement(on ? await api.statement() : null);
  }, []);
  // Hydrate from the backend: which sources exist and are on, today's date, and the statement already loaded.
  const refresh = useCallback(async () => {
    try {
      const r = await api.servers();
      setServers(r.servers);
      setToday(r.today);
      setLive(true);
      setApiError("");
      await loadStatement(r.servers.some((s) => s.id === "finance" && s.status === "connected"));
    } catch (e) {
      setLive(false);
      setApiError((e as Error).message);
    }
  }, [loadStatement]);
  useEffect(() => {
    void refresh();
    const key = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (
        e.key.toLowerCase() === "d" &&
        !e.ctrlKey &&
        !e.metaKey &&
        !["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName)
      ) {
        e.preventDefault();
        setDemo((x) => !x);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [refresh]);
  useEffect(() => {
    if (d.phase === "done") {
      setTab("verdict");
      setJustConnected(false);
    }
  }, [d.phase]);
  const closeSetup = useCallback(() => setSetup(false), []);
  const closeConnect = useCallback(() => setConnect(false), []);
  const closeDemo = useCallback(() => setDemo(false), []);
  // The Bookings window: everything the agent put on hold, ready for your OK, plus what you confirmed or let go.
  const [bookings, setBookings] = useState<Approval[]>([]);
  const [bookingsOpen, setBookingsOpen] = useState(false);
  const refreshBookings = useCallback(() => {
    api.actions().then(setBookings, () => undefined); // the badge is a nice-to-have; the window shows errors itself
  }, []);
  useEffect(() => {
    if (d.phase === "done" || d.phase === "idle") refreshBookings();
  }, [d.phase, refreshBookings]);
  const closeBookings = useCallback(() => setBookingsOpen(false), []);
  const openBookings = () => {
    refreshBookings();
    setBookingsOpen(true);
  };
  const bookingChanged = (a: Approval) => {
    setBookings((all) => all.map((x) => (x.id === a.id ? a : x)));
    d.updateApproval(a);
  };
  const waiting = bookings.filter((b) => b.status === "pending").length;
  const ORDER = ["pending", "confirmed", "approving", "declined", "expired", "failed"];
  const sortedBookings = [...bookings].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
  const ask = (q = question, quick = false) => {
    if (busy) return;
    const text = q.trim();
    if (!text) {
      setAskError("Type a question or choose one below.");
      return;
    }
    setAskError("");
    setQuestion(text);
    setAsked(text);
    setHighlight("");
    setTab("verdict");
    return d.run(text, servers, slow, quick);
  };
  // Voice (src/voice.ts): Gemini Live listens and speaks; every request it hears runs here, exactly like typing.
  const voiceRef = useRef<Voice | null>(null);
  const [voice, setVoice] = useState<"off" | "listening" | "thinking" | "speaking" | "ready">("off");
  const [caption, setCaption] = useState("");
  const [voiceError, setVoiceError] = useState("");
  const heard = useRef("");
  const replied = useRef(false); // Orbit has started answering this turn
  const handsFree = useRef(false); // this turn began with "Hey Orbit": the mic closes by itself
  const quiet = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const onVoice = useRef<(e: VoiceEvent) => void>(() => undefined);
  const getVoice = () => (voiceRef.current ??= new Voice((e) => onVoice.current(e)));
  // "Hey Orbit" (src/wake.ts): an opt-in switch. Listening pauses during a turn and resumes after Orbit has spoken.
  const [wakeOn, setWakeOn] = useState(false);
  const [wakeHeard, setWakeHeard] = useState(""); // what the browser is transcribing: shows why a wake was missed
  const wakeOnRef = useRef(false);
  const wakeRef = useRef<WakeWord | null>(null);
  const onWake = useRef<(rest: string) => void>(() => undefined);
  const listenForWake = () => {
    if (!wakeOnRef.current) return;
    (wakeRef.current ??= new WakeWord((rest) => onWake.current(rest), (msg) => {
      setVoiceError(msg);
      wakeOnRef.current = false;
      setWakeOn(false);
    }, setWakeHeard)).start();
  };
  const closeMic = () => {
    clearTimeout(quiet.current);
    if (voiceRef.current?.listening) voiceRef.current.stop();
  };
  const startTalking = async (hands: boolean) => {
    setVoiceError("");
    heard.current = "";
    replied.current = false;
    handsFree.current = hands;
    setCaption("");
    wakeRef.current?.stop();
    const v = getVoice();
    try {
      await v.start();
      setVoice("listening");
      if (hands) // nothing said after "Hey Orbit": back to waiting for it
        quiet.current = setTimeout(() => {
          if (!heard.current) {
            closeMic();
            setVoice("ready");
            listenForWake();
          }
        }, 8000);
    } catch (err) {
      setVoiceError((err as Error).message || "Orbit can't use the microphone.");
      setVoice(v.connected ? "ready" : "off");
      listenForWake();
    }
  };
  onWake.current = (rest) => {
    if (rest.split(/\s+/).length >= 2) {
      // "Hey Orbit, can I buy a table?" in one breath: Live takes the request as text
      setVoiceError("");
      setQuestion(rest);
      setCaption("");
      replied.current = false;
      setVoice("thinking");
      getVoice().say(rest).catch((err: Error) => {
        setVoiceError(err.message);
        listenForWake();
      });
    } else {
      void startTalking(true);
    }
  };
  onVoice.current = (e) => {
    if (e.type === "heard") {
      clearTimeout(quiet.current);
      heard.current += e.text;
      setQuestion(heard.current.trim());
    } else if (e.type === "ask") {
      if (handsFree.current) closeMic();
      setVoice("thinking");
      setCaption("");
      void Promise.resolve(ask(e.request)).then((r) => voiceRef.current?.result(e.id, voiceSummary(r ?? null)));
    } else if (e.type === "said") {
      if (handsFree.current) closeMic();
      replied.current = true;
      setVoice("speaking");
      setCaption((c) => c + e.text);
    } else if (e.type === "turn_done") {
      setVoice((v) => (v === "listening" ? v : "ready"));
      if (replied.current) {
        replied.current = false;
        // after Orbit's voice has finished playing, so it can't wake itself
        setTimeout(listenForWake, ((voiceRef.current?.playbackLeft ?? 0) + 0.6) * 1000);
      }
    } else if (e.type === "interrupted") {
      voiceRef.current?.hush();
    } else if (e.type === "error") {
      setVoiceError(e.text);
    } else if (e.type === "closed") {
      setVoice("off");
      listenForWake();
    }
  };
  useEffect(
    () => () => {
      wakeRef.current?.stop();
      voiceRef.current?.close();
    },
    [],
  );
  const toggleMic = async () => {
    if (voice === "listening") {
      closeMic();
      setVoice("thinking");
      return;
    }
    await startTalking(false);
  };
  const toggleWake = () => {
    const on = !wakeOn;
    wakeOnRef.current = on;
    setWakeOn(on);
    setVoiceError("");
    if (on) listenForWake();
    else wakeRef.current?.stop();
  };
  const endVoice = () => {
    closeMic();
    voiceRef.current?.close();
    setVoice("off");
    setCaption("");
  };
  const notify = (message: string, action: () => void, label: string) =>
    setNudges((n) => [...n, { id: Date.now(), message, action, label }].slice(-3));
  const contextChanged = (message: string) => {
    if (d.verdict) notify(message, () => ask(asked), "Ask again");
  };
  // On = plug the server in, Off = unplug it: the backend registry decides what any answer can read.
  const setSource = async (id: string, on: boolean) => {
    try {
      const r = await api.setSource(id, on);
      setServers(r.servers);
      if (id === "finance") await loadStatement(on);
      contextChanged("Your sources changed. Ask again to see the new answer.");
    } catch (e) {
      setApiError((e as Error).message);
    }
  };
  const openBalance = () => {
    setBalanceOnly(true);
    setSetup(true);
  };
  const openSetup = () => {
    setBalanceOnly(false);
    setSetup(true);
  };
  const reset = async () => {
    d.reset();
    setQuestion("");
    setAsked(HERO);
    setTab("verdict");
    setSlow(false);
    setHighlight("");
    setNudges([]);
    setJustConnected(false);
    setConnect(false);
    setBalanceOnly(false);
    setAskError("");
    setDemo(false);
    setSetup(false);
    setInsights(false);
    setDismissed(null);
    if (financeOn) await setSource("finance", false); // the demo starts without the budget
  };
  const openInsights = () => {
    setTab("receipt");
    setInsights(true);
  };
  const closeInsights = useCallback(() => setInsights(false), []);
  // Small talk, the weather, "what did I spend": a short reply under the question, not a plan to scroll through.
  const chat = (d.pending || d.verdict)?.verdict === "info";
  const hasPlan = Boolean(d.verdict || d.pending || busy || d.error) && !chat;
  // A plan the engine cleared with your money checked (the same rule Guardian uses for holds) can be put on hold.
  const canHold = d.phase === "done" && !chat && !d.approvals.length && Boolean(d.verdict) &&
    ["yes", "yes_with_conditions", "risky"].includes(d.verdict!.verdict) && d.verdict!.numbers.balance != null &&
    Boolean(d.verdict!.numbers.breakdown?.length);
  const flagged = d.verdict?.evidence.find((e) => INJECTED.test(e.finding));
  const scrollToPlan = () =>
    document.getElementById("plan")?.scrollIntoView({
      behavior: reduced ? "auto" : "smooth",
      block: "start",
    });
  return (
    <>
      <Atmosphere />
      <ContextConnections busy={busy} active={d.active} servers={servers} />
      <a href="#ask-input" className="skip-link">
        Skip to your question
      </a>
      <header className="calm-header">
        <a href="#" className="brand" aria-label="Orbit home">
          <span className="logo-mark">
            <Eye size={25} />
          </span>
          <span>
            ORBIT<span className="brand-period">.</span>
          </span>
        </a>
        <span className="header-note">A LITTLE MORE CLARITY.</span>
        <div className="calm-header-actions">
          <button
            className="header-budget"
            aria-label="Your balance"
            onClick={openBalance}
          >
            <Wallet size={18} />
            <span>{statement ? <AnimatedAmount value={statement.balance} /> : "Add balance"}</span>
          </button>
          <button
            className="header-budget"
            aria-label={`Your bookings${waiting ? `, ${waiting} waiting for your OK` : ""}`}
            onClick={openBookings}
          >
            <Ticket size={18} />
            <span>Bookings</span>
            {waiting > 0 && <span className="booking-badge">{waiting}</span>}
          </button>
          {google?.configured && (
            <button
              className="header-budget"
              aria-label={google.connected ? `Google connected as ${google.email}. Disconnect` : "Connect Google"}
              title={google.connected ? `${google.email}: click to disconnect` : "Let Orbit send emails and add events you approve"}
              onClick={toggleGoogle}
            >
              <CalendarCheck size={18} />
              <span>{google.connected ? "Google ✓" : "Connect Google"}</span>
            </button>
          )}
          <button
            className="discreet-button"
            aria-label="Demo controls"
            onClick={() => setDemo(true)}
          >
            <SlidersHorizontal size={20} />
          </button>
          {onSignOut && (
            <button className="discreet-button" aria-label="Sign out" title="Sign out" onClick={onSignOut}>
              <LogOut size={20} />
            </button>
          )}
        </div>
      </header>
      {googleNote && (
        <p className="google-note" role="status">
          {googleNote}
          <button className="discreet-button" aria-label="Dismiss" onClick={() => setGoogleNote("")}>
            <X size={16} />
          </button>
        </p>
      )}
      <SourceDock
        servers={servers}
        disabled={busy}
        active={d.active}
        returned={d.returned}
        phase={d.phase}
        onPermission={(id, p) => void setSource(id, p === "allow")}
        onConnect={() => setConnect(true)}
      />
      <main className="calm-workspace">
        <section className="landing" aria-labelledby="landing-heading">
          <span className="landing-eyebrow">YOUR PLANS. YOUR PRIORITIES.</span>
          <h1 id="landing-heading">
            <span className="headline-mask">
              <motion.span
                className="headline-line"
                initial={reduced ? false : { y: "105%" }}
                animate={{ y: 0 }}
                transition={{ duration: reduced ? 0 : 0.7, ease: revealEase }}
              >
                BIG PLANS.
              </motion.span>
            </span>
            <span className="headline-mask">
              <motion.span
                className="headline-line"
                initial={reduced ? false : { y: "105%" }}
                animate={{ y: 0 }}
                transition={{
                  duration: reduced ? 0 : 0.7,
                  delay: reduced ? 0 : 0.08,
                  ease: revealEase,
                }}
              >
                CLEAR ANSWERS.
              </motion.span>
            </span>
          </h1>
          <p className="landing-description">
            A trip. A purchase. A change of plans.
            <br />
            Let’s work out what fits your life.
          </p>
          <motion.form
            className="calm-ask"
            initial={reduced ? false : { scale: 0.98, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{
              duration: reduced ? 0 : 0.6,
              delay: reduced ? 0 : 0.78,
              ease: revealEase,
            }}
            onSubmit={(e) => {
              e.preventDefault();
              ask(question);
            }}
          >
            <label htmlFor="ask-input" className="sr-only">
              What would you like to decide?
            </label>
            <textarea
              id="ask-input"
              rows={2}
              placeholder="Can I afford a Goa trip next weekend?"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !busy) {
                  e.preventDefault();
                  ask(question);
                }
              }}
            />
            <button
              type="button"
              className={`mic-button mic-${voice}`}
              onClick={() => void toggleMic()}
              aria-pressed={voice === "listening"}
              aria-label={voice === "listening" ? "Stop talking" : "Talk to Orbit"}
              title={voice === "listening" ? "Stop talking" : "Talk to Orbit"}
            >
              {voice === "listening" ? <Square size={18} /> : <Mic size={20} />}
            </button>
            <Button
              type="submit"
              tone="forest"
              disabled={busy}
              aria-label="Ask Orbit"
            >
              {busy ? "Checking…" : "Help me decide"}
            </Button>
          </motion.form>
          {askError && (
            <p className="field-error" role="alert">
              {askError}
            </p>
          )}
          {voice !== "off" && (
            <div className="voice-bar" role="status">
              <span className={`voice-dot voice-dot-${voice}`} aria-hidden />
              <div>
                <strong>
                  {{
                    listening: "Listening… tap ■ when you're done",
                    thinking: "Working on it…",
                    speaking: "Orbit is speaking",
                    ready: "Tap the mic to talk again",
                  }[voice]}
                </strong>
                {caption && <p>“{caption.trim()}”</p>}
              </div>
              <button className="text-button" onClick={endVoice}>
                End voice
              </button>
            </div>
          )}
          {voiceError && (
            <p className="field-error" role="alert">
              {voiceError}
            </p>
          )}
          {wakeSupported() && (
            <button
              type="button"
              className={`wake-switch${wakeOn ? " wake-on" : ""}`}
              role="switch"
              aria-checked={wakeOn}
              onClick={toggleWake}
              title="Listens for “Hey Orbit” while this tab is open. Chrome / Edge transcribe that audio."
            >
              <span className="wake-track" aria-hidden>
                <span className="wake-knob" />
              </span>
              “Hey Orbit” {wakeOn ? "on: say it any time" : "off"}
            </button>
          )}
          {wakeOn && voice === "off" && (
            <p className="wake-heard" aria-live="polite">
              {wakeHeard ? `Heard: “${wakeHeard.trim()}”` : "Listening for “Hey Orbit”…"}
            </p>
          )}
          <motion.div
            className="calm-suggestions"
            aria-label="Example questions"
            initial={reduced ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{
              duration: reduced ? 0 : 0.6,
              delay: reduced ? 0 : 0.9,
              ease: revealEase,
            }}
          >
            {prompts.map((p) => (
              <button key={p.q} disabled={busy} onClick={() => ask(p.q)}>
                {p.label}
              </button>
            ))}
          </motion.div>
          <p className="landing-trust">
            <ShieldCheck size={16} />
            You choose what to share. You have the final say.
          </p>
          {busy && (
            <div className="landing-progress" role="status">
              <span>
                {d.phase === "discovering"
                  ? d.step ? `${d.step}…` : "Looking at the information you allow…"
                  : d.phase === "calling"
                    ? "Checking your dates and budget…"
                    : "Bringing your plan together…"}
              </span>
              <button onClick={d.skip}>Show the answer now</button>
            </div>
          )}
          {canHold && (
            <div className="hold-offer">
              <Button tone="forest" onClick={() => ask(`Book this plan: ${asked}`)}>
                Hold these for my OK
              </Button>
              <span>Free and reversible. Nothing is booked until you approve it.</span>
            </div>
          )}
          {d.phase === "done" && <Approvals items={d.approvals} onChange={bookingChanged} />}
          {d.phase === "done" && chat && d.verdict && (
            <div className="agent-reply" role="status">
              <MessageCircle size={20} aria-hidden />
              <div>
                <p>{d.verdict.headline}</p>
                {d.verdict.explanation && <p className="agent-reply-more">{d.verdict.explanation}</p>}
              </div>
            </div>
          )}
          {d.phase === "done" && !justConnected && !chat && (
            <button className="see-plan-button" onClick={scrollToPlan}>
              Your plan is ready. Scroll to explore.
            </button>
          )}
          {justConnected && (
            <div className="budget-added">
              <Check size={18} />
              <span>Your budget is ready to include.</span>
              <Button tone="forest" onClick={() => ask(asked)}>
                Check my plan again
              </Button>
            </div>
          )}
          {live === false && (
            <div className="quiet-notice" role="alert">
              <WifiOff size={17} />
              <span>
                {apiError} Start the MCP servers (run_servers.py) and the backend (backend/main.py), then retry.
              </span>
              <button onClick={() => void refresh()}>Retry</button>
            </div>
          )}
          {flagged && dismissed !== d.verdict && (
            <div className="quiet-notice" role="alert">
              <ShieldCheck size={18} />
              <span>
                We ignored an unsafe instruction in your email. Nothing was
                changed.
              </span>
              <button onClick={openInsights}>See details</button>
              <button
                aria-label="Dismiss safety notice"
                onClick={() => setDismissed(d.verdict)}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {d.error && (
            <div className="quiet-notice" role="alert">
              <Info size={18} />
              <span>We couldn’t check your information. {d.error}</span>
              <Button onClick={() => ask(asked)}>Try again</Button>
            </div>
          )}
        </section>
        {hasPlan && (
          <PlanJourney
            verdict={d.pending || d.verdict}
            previous={d.previous}
            servers={servers}
            statement={statement}
            today={today}
            busy={busy}
            onConnect={() => setConnect(true)}
            onSetup={openSetup}
            onBalance={openBalance}
            onInsights={openInsights}
          />
        )}
        {!hasPlan && (
          <div className="landing-endnote">
            <span>ONE QUESTION. THE WHOLE PICTURE.</span>
            <p>Start with what’s on your mind.</p>
          </div>
        )}
      </main>
      <footer className="calm-footer">
        <span>
          ORBIT <strong>//</strong> YOU HAVE THE FINAL SAY.
        </span>
        <button onClick={openSetup}>Add a statement</button>
        <span>AI that decides with you, not for you.</span>
      </footer>
      <div className="toast-stack" aria-live="polite">
        <AnimatePresence>
          {nudges.map((n) => (
            <NudgeToast
              key={n.id}
              n={n}
              onDismiss={() =>
                setNudges((ns) => ns.filter((x) => x.id !== n.id))
              }
            />
          ))}
        </AnimatePresence>
      </div>
      {insights && (
        <Modal
          title="THE DETAILS BEHIND YOUR PLAN."
          label="detailed_insights"
          onClose={closeInsights}
        >
          <p>
            See what was read, what was left out, and how this answer was
            formed.
          </p>
          <Suspense fallback={<Skeleton />}>
            <div className="insights-layout">
              <EvidenceGraph
                servers={servers}
                phase={d.phase}
                active={d.active}
                returned={d.returned}
                verdict={d.pending || d.verdict}
                question={asked}
                highlight={highlight}
                skip={d.skip}
                slow={slow}
              />
              <Panels
                tab={tab}
                setTab={setTab}
                verdict={d.verdict}
                previous={d.previous}
                phase={d.phase}
                servers={servers}
                trace={d.trace}
                statement={statement}
                today={today}
                onBalance={() => {
                  setInsights(false);
                  openBalance();
                }}
                onHighlight={setHighlight}
                error={d.error}
                onRetry={() => ask(asked)}
                canAskAgain={justConnected}
                onAskAgain={() => ask(asked)}
                onSetup={() => {
                  setInsights(false);
                  openSetup();
                }}
              />
            </div>
          </Suspense>
          {flagged && (
            <div className="insights-injection">
              <strong>UNTRUSTED TEXT. NO ACTIONS TAKEN.</strong>
              <p>Flagged by the engine:</p>
              <mark>{flagged.finding}</mark>
              <p className="mono">0 WRITE TOOLS EXECUTED</p>
            </div>
          )}
        </Modal>
      )}
      {setup && (
        <SetupDialog
          onClose={closeSetup}
          onDone={(info) => {
            setStatement(info);
            contextChanged("Your statement changed. Ask again to see the new answer.");
          }}
          statement={statement}
          financeOn={financeOn}
          onFinanceOn={() => setSource("finance", true)}
          balanceOnly={balanceOnly}
        />
      )}
      {connect && (
        <ConnectDialog
          onClose={closeConnect}
          onConnected={(next) => {
            setServers(next);
            setJustConnected(true);
            setHighlight("Finance");
            void loadStatement(true);
          }}
        />
      )}
      {bookingsOpen && (
        <Modal title="READY WHEN YOU ARE." label="your_bookings" onClose={closeBookings}>
          {sortedBookings.length ? (
            <Approvals items={sortedBookings} onChange={bookingChanged} inWindow />
          ) : (
            <p className="approvals-empty">
              Nothing on hold yet. Ask Orbit to book something, like “Book a Goa trip next weekend”, and it will show
              up here for your OK.
            </p>
          )}
        </Modal>
      )}
      {demo && (
        <Modal
          title="READY FOR THE DEMO."
          onClose={closeDemo}
          label="demo_controls"
        >
          <p>Repeat the key moments. Same inputs, same sequence.</p>
          <div className="demo-actions">
            <Button
              tone="orange"
              disabled={busy}
              onClick={() => {
                setDemo(false);
                ask(HERO);
              }}
            >
              Run hero question
            </Button>
            <Button
              tone="violet"
              onClick={() => {
                setDemo(false);
                if (financeOn) void setSource("finance", false);
                else setConnect(true);
              }}
            >
              {financeOn ? "Disconnect" : "Connect"} Finance
            </Button>
            <Button aria-pressed={slow} onClick={() => setSlow((s) => !s)}>
              Slow animations ×2 {slow ? "ON" : "OFF"}
            </Button>
            <Button onClick={() => void reset()}>
              <RefreshCw size={16} />
              Reset demo
            </Button>
          </div>
          <p className="small-note">
            Press D to open or close this drawer. Press Escape to close.
          </p>
        </Modal>
      )}
    </>
  );
}
