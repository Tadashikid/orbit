import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useMotionPreferences } from "../hooks/useMotionPreferences";
import type { Server } from "../types";

const contours = Array.from({ length: 16 }, (_, ring) => {
  const points = Array.from({ length: 81 }, (_, step) => {
    const angle = (step / 80) * Math.PI * 2;
    const radius =
      110 +
      ring * 37 +
      Math.sin(angle * 3 + ring * 0.1) * 22 +
      Math.cos(angle * 5) * 9;
    return `${step ? "L" : "M"}${(790 + Math.cos(angle) * radius * 1.5).toFixed(1)},${(510 + Math.sin(angle) * radius).toFixed(1)}`;
  });
  return points.join(" ") + " Z";
});
export function Atmosphere() {
  return (
    <>
      <div className="page-atmosphere" aria-hidden="true">
        <svg
          className="contour-layer"
          viewBox="0 0 1600 1000"
          preserveAspectRatio="xMidYMid slice"
        >
          <g fill="none" stroke="var(--forest-800)" strokeWidth="1">
            {contours.map((d, i) => (
              <path key={i} d={d} vectorEffect="non-scaling-stroke" />
            ))}
          </g>
        </svg>
        <div className="background-grid" />
      </div>
      <svg
        className="paper-grain"
        aria-hidden="true"
        width="100%"
        height="100%"
      >
        <filter id="orbit-paper-grain" x="0" y="0" width="100%" height="100%">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.85"
            numOctaves="3"
            seed="7"
            result="noise"
          />
          <feColorMatrix
            in="noise"
            type="matrix"
            values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0"
            result="noise-alpha"
          />
          <feComposite in="SourceGraphic" in2="noise-alpha" operator="in" />
        </filter>
        <rect
          width="100%"
          height="100%"
          fill="var(--ink)"
          filter="url(#orbit-paper-grain)"
        />
      </svg>
    </>
  );
}

type Connection = {
  id: string;
  path: string;
  enabled: boolean;
  active: boolean;
};
export function ContextConnections({
  busy,
  active,
  servers,
}: {
  busy: boolean;
  active: string[];
  servers: Server[];
}) {
  const { reduced } = useMotionPreferences();
  const [lines, setLines] = useState<Connection[]>([]);
  const [idlePulse, setIdlePulse] = useState(0);
  const [visible, setVisible] = useState(true);
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      if (reduced || document.hidden) {
        setLines((previous) => (previous.length ? [] : previous));
        return;
      }
      const ask = document.querySelector(".calm-ask")?.getBoundingClientRect();
      if (
        !ask ||
        ask.width === 0 ||
        ask.bottom < 0 ||
        ask.top > window.innerHeight
      ) {
        setLines((previous) => (previous.length ? [] : previous));
        return;
      }
      setViewport((previous) =>
        previous.width === window.innerWidth &&
        previous.height === window.innerHeight
          ? previous
          : { width: window.innerWidth, height: window.innerHeight },
      );
      const mobile = window.matchMedia("(max-width: 767px)").matches;
      const startX = mobile ? ask.left + ask.width / 2 : ask.left;
      const startY = mobile ? ask.bottom : ask.top + ask.height / 2;
      setLines(
        [
          ...document.querySelectorAll<HTMLElement>(
            ".dock-icon[data-source-id]",
          ),
        ].map((icon) => {
          const r = icon.getBoundingClientRect();
          const endX = mobile ? r.left + r.width / 2 : r.right;
          const endY = mobile ? r.top : r.top + r.height / 2;
          const path = mobile
            ? `M ${startX} ${startY} C ${startX} ${startY + 30}, ${endX} ${endY - 30}, ${endX} ${endY}`
            : `M ${startX} ${startY} C ${startX - 45} ${startY}, ${endX + 35} ${endY}, ${endX} ${endY}`;
          return {
            id: icon.dataset.sourceId!,
            path,
            enabled: icon.classList.contains("enabled"),
            active: active.includes(icon.dataset.sourceId!),
          };
        }),
      );
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    const visibility = () => {
      setVisible(!document.hidden);
      schedule();
    };
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule, { passive: true });
    document.addEventListener("visibilitychange", visibility);
    const observer = new ResizeObserver(schedule);
    const ask = document.querySelector(".calm-ask");
    if (ask) observer.observe(ask);
    const dock = document.querySelector(".source-dock");
    if (dock) observer.observe(dock);
    schedule();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [reduced, active, servers]);
  useEffect(() => {
    if (reduced || busy || !visible) return;
    const timer = setInterval(() => setIdlePulse((n) => n + 1), 9000);
    return () => clearInterval(timer);
  }, [busy, reduced, visible]);
  if (reduced || !visible || !lines.length) return null;
  const enabled = lines.filter((l) => l.enabled);
  const pulseId = enabled.length
    ? enabled[(idlePulse - 1 + enabled.length) % enabled.length].id
    : "";
  return (
    <svg
      className="context-connections"
      viewBox={`0 0 ${viewport.width} ${viewport.height}`}
      aria-hidden="true"
    >
      {lines.map((line, i) => (
        <g key={line.id}>
          <motion.path
            d={line.path}
            fill="none"
            stroke="var(--mint-300)"
            strokeWidth="1"
            initial={{ pathLength: 0 }}
            animate={{
              pathLength: busy ? 1 : 0,
              opacity: line.active ? 0.8 : 0.18,
            }}
            transition={{
              duration: reduced ? 0 : 0.6,
              delay: busy ? i * 0.12 : 0,
            }}
          />
          {!busy && idlePulse > 0 && line.id === pulseId && (
            <motion.g
              key={idlePulse}
              initial={{ opacity: 0 }}
              animate={{ opacity: [0, 0.35, 0] }}
              transition={{ duration: 1.3 }}
            >
              <circle r="2" fill="var(--mint-300)">
                <animateMotion
                  dur="1.3s"
                  path={line.path}
                  repeatCount="1"
                  fill="freeze"
                />
              </circle>
            </motion.g>
          )}
        </g>
      ))}
    </svg>
  );
}
