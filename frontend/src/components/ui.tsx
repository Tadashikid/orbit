import { animate, useInView } from "framer-motion";
import {
  useMotionPreferences,
  revealEase,
} from "../hooks/useMotionPreferences";
import { Children } from "react";
import {
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import {
  X,
  CalendarDays,
  ListChecks,
  Wallet,
  Plane,
  Tag,
  MapPin,
  Eye,
} from "lucide-react";
export const money = (n: number) =>
  `${n < 0 ? "−" : ""}Rs ${Math.abs(Math.round(n)).toLocaleString("en-IN")}`;
export const shortDate = (d: string) =>
  new Date(d).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
export const icons: Record<string, typeof Eye> = {
  Calendar: CalendarDays,
  Tasks: ListChecks,
  Finance: Wallet,
  Travel: Plane,
  "Price Check": Tag,
  Location: MapPin,
};
export function Card({
  children,
  className = "",
  ...props
}: HTMLAttributes<HTMLElement>) {
  return (
    <section
      className={`card ${className.includes("terminal") ? "surface-forest" : "surface-paper"} ${className}`}
      {...props}
    >
      {children}
    </section>
  );
}
export function Button({
  children,
  className = "",
  tone = "paper",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: string }) {
  return (
    <button
      className={`button ${className.includes("surface-paper") ? "surface-paper" : "surface-forest"} ${tone} ${className}`}
      {...props}
    >
      <span className="button-content">
        {Children.map(children, (child) =>
          typeof child === "string" ? (
            <span className="button-label">{child}</span>
          ) : (
            child
          ),
        )}
      </span>
    </button>
  );
}
export function Chip({
  children,
  tone = "paper",
  className = "",
}: {
  children: ReactNode;
  tone?: string;
  className?: string;
}) {
  return (
    <span
      className={`chip ${["forest", "lime", "violet"].includes(tone) ? "surface-forest" : "surface-paper"} ${tone} ${className}`}
    >
      {children}
    </span>
  );
}
export function Pill({ children }: { children: ReactNode }) {
  return <span className="pill surface-forest">// {children}</span>;
}
export function TerminalCard({
  children,
  filename,
  tag,
  actions,
}: {
  children: ReactNode;
  filename: string;
  tag?: string;
  actions?: ReactNode;
}) {
  return (
    <Card className="terminal">
      <header>
        <span className="traffic">
          <i />
          <i />
          <i />
        </span>
        <span>{filename}</span>
        <span className="terminal-tag">{tag}</span>
        {actions}
      </header>
      <div className="terminal-body">{children}</div>
    </Card>
  );
}
export function Modal({
  title,
  children,
  onClose,
  label = "dialog",
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    const items = () =>
      Array.from(
        ref.current?.querySelectorAll<HTMLElement>(
          'button,input,select,textarea,[tabindex="0"]',
        ) || [],
      ).filter((e) => !e.hasAttribute("disabled"));
    items()[0]?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const all = items();
        const first = all[0],
          last = all.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, [onClose]);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal card surface-paper"
        role="dialog"
        aria-modal="true"
        aria-labelledby={label}
        ref={ref}
      >
        <div className="modal-heading">
          <Pill>{label.replaceAll("_", " ")}</Pill>
          <Button
            className="icon-button"
            aria-label="Close dialog"
            onClick={onClose}
          >
            <X size={20} />
          </Button>
        </div>
        <h2 id={label}>{title}</h2>
        {children}
      </div>
    </div>
  );
}
export function Skeleton() {
  return (
    <div className="skeletons" aria-label="Loading context">
      <div />
      <div />
      <div />
    </div>
  );
}

export function AnimatedAmount({
  value,
  format = "money",
}: {
  value: number;
  format?: "money" | "number";
}) {
  const { reduced } = useMotionPreferences();
  const ref = useRef<HTMLSpanElement>(null);
  const visible = useInView(ref, { once: true, amount: 0.15 });
  const formatted = (n: number) =>
    format === "money" ? money(n) : Math.round(n).toLocaleString("en-IN");
  const [display, setDisplay] = useState(reduced ? value : 0);
  useEffect(() => {
    if (reduced) {
      setDisplay(value);
      return;
    }
    if (!visible) return;
    const anim = animate(0, value, {
      duration: 0.8,
      ease: revealEase,
      onUpdate: setDisplay,
    });
    return () => anim.stop();
  }, [value, reduced, visible]);
  return (
    <span
      ref={ref}
      className="count-figure"
      data-figure={formatted(value)}
      aria-label={formatted(value)}
    >
      <span aria-hidden="true">{formatted(reduced ? value : display)}</span>
    </span>
  );
}
