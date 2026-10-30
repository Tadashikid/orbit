import { useCallback, useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  useMotionPreferences,
  revealEase,
} from "../hooks/useMotionPreferences";
import { Plus, Eye, ShieldCheck, Check } from "lucide-react";
import type { Server, Permission, Phase } from "../types";
import { Button, Modal, icons } from "./ui";
export const sourceLabels: Record<string, string> = {
  calendar: "Schedule",
  tasks: "To-dos",
  finance: "Budget",
  travel: "Travel",
  price: "Prices",
  location: "Location",
};
export default function SourceDock({
  servers,
  onPermission,
  onConnect,
  disabled = false,
  active = [],
  returned = [],
  phase = "idle",
}: {
  servers: Server[];
  onPermission: (id: string, p: Permission) => void;
  onConnect: () => void;
  disabled?: boolean;
  active?: string[];
  returned?: string[];
  phase?: Phase;
}) {
  const { reduced } = useMotionPreferences();
  const [selected, setSelected] = useState<string | null>(null);
  const [indicator, setIndicator] = useState("calendar");
  const [checks, setChecks] = useState<string[]>([]);
  useEffect(() => {
    if (phase === "idle") {
      setChecks([]);
      return;
    }
    setChecks(returned);
    if (phase !== "done") return;
    const timer = setTimeout(() => setChecks([]), reduced ? 0 : 1200);
    return () => clearTimeout(timer);
  }, [phase, returned, reduced]);
  const close = useCallback(() => setSelected(null), []);
  const current = servers.find((s) => s.id === selected);
  return (
    <>
      <motion.nav
        className="source-dock surface-forest"
        aria-label="Your information sources"
        initial={reduced ? false : { x: -8, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        transition={{
          duration: reduced ? 0 : 0.6,
          delay: reduced ? 0 : 1.02,
          ease: revealEase,
        }}
      >
        <div className="dock-heading">
          <Eye size={19} />
        </div>
        {servers.map((s) => {
          const Icon = icons[s.name] ?? Eye;
          const VerifiedIcon = checks.includes(s.id) ? Check : Icon;
          return (
            <button
              key={s.id}
              className={`dock-icon ${s.status === "connected" && s.permission !== "off" ? "enabled" : ""} ${active.includes(s.id) && !returned.includes(s.id) ? "reading" : ""}`}
              data-source-id={s.id}
              title={sourceLabels[s.id] ?? s.name}
              aria-label={`Manage ${sourceLabels[s.id] ?? s.name}`}
              aria-haspopup="dialog"
              onPointerEnter={() => setIndicator(s.id)}
              onFocus={() => setIndicator(s.id)}
              onClick={() => {
                setIndicator(s.id);
                setSelected(s.id);
              }}
            >
              <VerifiedIcon size={21} />
              <span className="dock-tooltip surface-forest">
                {sourceLabels[s.id] ?? s.name}
              </span>
              {s.status === "connected" && s.permission !== "off" && (
                <motion.span
                  className="dock-indicator"
                  layoutId={
                    !reduced && indicator === s.id
                      ? "rail-active-indicator"
                      : undefined
                  }
                  transition={{ type: "spring", duration: 0.24, bounce: 0.12 }}
                />
              )}
            </button>
          );
        })}
        <div className="dock-divider" />
        <button
          className="dock-icon"
          title="Add a source"
          aria-label="Add a source"
          onClick={onConnect}
        >
          <Plus size={21} />
          <span className="dock-tooltip surface-forest">Add a source</span>
        </button>
      </motion.nav>
      {current && (
        <Modal
          title={`YOUR ${sourceLabels[current.id] ?? current.name}. YOUR CHOICE.`}
          label="source_settings"
          onClose={close}
        >
          <p>Choose when Orbit can use this information.</p>
          <div className="source-readiness">
            <Check size={17} />
            {current.status === "connected"
              ? "This source is ready to use."
              : current.status === "error"
                ? "This source needs attention: it didn’t answer. Is run_servers.py running?"
                : "This source is switched off."}
          </div>
          <div
            className="source-mode"
            aria-label={`${sourceLabels[current.id] ?? current.name} access mode`}
          >
            {(
              [
                { value: "off", label: "Off" },
                { value: "allow", label: "On" },
              ] as const
            ).map((p) => (
              <button
                key={p.value}
                aria-pressed={current.permission === p.value}
                disabled={disabled}
                className={current.permission === p.value ? "selected" : ""}
                onClick={() => onPermission(current.id, p.value)}
              >
                {p.label}
              </button>
            ))}
          </div>
          <p className="mode-explanation">
            {current.permission === "off"
              ? "This information will be left out of new answers."
              : "Read this information when it helps answer your question."}
          </p>
          {current.status !== "connected" && current.id === "finance" && (
            <Button
              tone="forest"
              onClick={() => {
                close();
                onConnect();
              }}
            >
              Add a source
            </Button>
          )}
          <div className="plain-privacy">
            <ShieldCheck size={18} />
            <p>
              Reading information doesn’t allow Orbit to change it. Changes
              always need your approval.
            </p>
          </div>
        </Modal>
      )}
    </>
  );
}
