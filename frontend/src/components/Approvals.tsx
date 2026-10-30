import { useState } from "react";
import { BedDouble, Check, Plane, ShieldCheck, ShoppingCart, X } from "lucide-react";
import { api } from "../api";
import type { Approval } from "../types";
import { Button, money } from "./ui";
const KIND = { flight: Plane, stay: BedDouble, order: ShoppingCart };
const time = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
// Holds the agent prepared. Nothing is booked or paid until you press Approve; the AI can't press it for you.
export default function Approvals({ items, onChange }: { items: Approval[]; onChange: (a: Approval) => void }) {
  const [busy, setBusy] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  if (!items.length) return null;
  const act = async (a: Approval, how: "approve" | "decline") => {
    setBusy(a.id);
    setErrors((e) => ({ ...e, [a.id]: "" }));
    try {
      onChange(await api[how](a));
    } catch (err) {
      setErrors((e) => ({ ...e, [a.id]: (err as Error).message }));
    } finally {
      setBusy("");
    }
  };
  return (
    <section className="approvals" aria-label="Waiting for your approval">
      <h2>Waiting for your OK</h2>
      <p className="approvals-note">
        <ShieldCheck size={16} />
        Orbit put these on hold. Nothing is booked or paid until you approve. Sandbox: no real bookings yet.
      </p>
      <ul>
        {items.map((a) => {
          const Icon = KIND[a.kind] ?? ShoppingCart;
          return (
            <li key={a.id} className={`approval approval-${a.status}`}>
              <Icon size={20} aria-hidden />
              <div className="approval-body">
                <strong>{a.summary}</strong>
                <span>
                  {money(a.amount)}
                  {a.status === "pending" && ` · held until ${time(a.expires_at)}`}
                </span>
                {a.status === "confirmed" && (
                  <span className="approval-done">
                    <Check size={16} /> Confirmed · {a.outcome?.reference}. {a.outcome?.payment}
                  </span>
                )}
                {["declined", "expired", "failed"].includes(a.status) && (
                  <span className="approval-done">
                    <X size={16} /> {a.status === "declined" ? "Let go" : a.status === "expired" ? "Hold expired" : "Couldn't confirm"}
                  </span>
                )}
                {errors[a.id] && (
                  <span className="approval-error" role="alert">
                    {errors[a.id]}
                  </span>
                )}
              </div>
              {a.status === "pending" && (
                <div className="approval-actions">
                  <Button tone="forest" disabled={busy === a.id} onClick={() => act(a, "approve")}>
                    Approve
                  </Button>
                  <Button className="surface-paper" disabled={busy === a.id} onClick={() => act(a, "decline")}>
                    Decline
                  </Button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
