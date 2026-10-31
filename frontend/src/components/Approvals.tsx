import { useState } from "react";
import { BedDouble, Check, Copy, ExternalLink, Plane, ShieldCheck, ShoppingCart, X } from "lucide-react";
import { api, type Profile } from "../api";
import type { Approval } from "../types";
import { Button, money } from "./ui";
const KIND = { flight: Plane, stay: BedDouble, order: ShoppingCart };
const time = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
const price = (a: Approval) =>
  !a.currency || a.currency === "INR"
    ? money(a.amount)
    : new Intl.NumberFormat("en-GB", { style: "currency", currency: a.currency }).format(a.amount);
// A Duffel hold can last days: show the date too once it isn't today.
const until = (iso: string) =>
  new Date(iso).toDateString() === new Date().toDateString()
    ? time(iso)
    : new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
// Your Profile as one block to paste into a store's checkout (a web page can't type into another site's form).
const forCheckout = (p: Profile) =>
  [`${p.first_name} ${p.last_name}`, p.phone, p.email, [p.address, p.city, p.state, p.pincode, p.country].filter(Boolean).join(", ")]
    .filter(Boolean)
    .join("\n");
// Holds the agent prepared. Nothing is booked or paid until you press Approve; the AI can't press it for you.
export default function Approvals({
  items,
  onChange,
  inWindow = false, // inside the Bookings window, whose title is the heading
  profile = null,
}: {
  items: Approval[];
  onChange: (a: Approval) => void;
  inWindow?: boolean;
  profile?: Profile | null;
}) {
  const [busy, setBusy] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  if (!items.length) return null;
  const [copied, setCopied] = useState("");
  const copy = async (a: Approval) => {
    try {
      await navigator.clipboard.writeText(forCheckout(profile!));
      setCopied(a.id);
    } catch {
      setErrors((e) => ({ ...e, [a.id]: "Couldn't copy: select the details and copy them yourself." }));
    }
  };
  // Shops and hotels: open their checkout (in the click, so it isn't blocked as a pop-up), then mark it approved.
  const checkout = (a: Approval) => {
    window.open(a.link, "_blank", "noopener,noreferrer");
    void act(a, "approve");
  };
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
    <section className={inWindow ? "approvals approvals-window" : "approvals"} aria-label="Your bookings">
      {!inWindow && <h2>Waiting for your OK</h2>}
      <p className="approvals-note">
        <ShieldCheck size={16} />
        Orbit put these on hold. Nothing is booked or paid until you approve. Shop and hotel cards open the store's
        checkout with your details ready: you review and pay there. Test mode: flights marked “Duffel
        test” are real Duffel holds paid from a test balance; the rest is a sandbox. No real money moves.
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
                  {price(a)}
                  {a.status === "pending" && ` · held until ${until(a.expires_at)}`}
                </span>
                {a.passenger && <span>Passenger: {a.passenger}</span>}
                {a.status === "pending" && a.link && (profile ? (
                  <span className="approval-details">
                    <span>For checkout: {forCheckout(profile).replaceAll("\n", " · ")}</span>
                    <button type="button" className="approval-store" onClick={() => copy(a)}>
                      <Copy size={14} aria-hidden /> {copied === a.id ? "Copied" : "Copy my details"}
                    </button>
                  </span>
                ) : (
                  <span>Add your details in Profile to have them ready for checkout.</span>
                ))}
                {a.status === "confirmed" && (
                  <span className="approval-done">
                    <Check size={16} /> Confirmed · {a.outcome?.reference}. {a.outcome?.payment}
                  </span>
                )}
                {a.status === "confirmed" && a.outcome?.notice && <span className="approval-done">{a.outcome.notice}</span>}
                {["declined", "expired", "failed"].includes(a.status) && (
                  <span className="approval-done">
                    <X size={16} /> {a.status === "declined" ? "Let go" : a.status === "expired" ? "Hold expired" : "Couldn't confirm"}
                  </span>
                )}
                {a.status !== "pending" && a.link?.startsWith("https://") && (
                  <a className="approval-store" href={a.link} target="_blank" rel="noopener noreferrer">
                    Checkout at {a.store || "the store"} <ExternalLink size={14} aria-hidden />
                  </a>
                )}
                {errors[a.id] && (
                  <span className="approval-error" role="alert">
                    {errors[a.id]}
                  </span>
                )}
              </div>
              {a.status === "pending" && (
                <div className="approval-actions">
                  {a.link?.startsWith("https://") ? (
                    <Button tone="forest" aria-label={`Checkout ${a.summary} at ${a.store || "the store"}`} disabled={busy === a.id}
                      onClick={() => checkout(a)}>
                      Checkout <ExternalLink size={14} aria-hidden />
                    </Button>
                  ) : (
                    <Button tone="forest" aria-label={`Approve ${a.summary}`} disabled={busy === a.id} onClick={() => act(a, "approve")}>
                      Approve
                    </Button>
                  )}
                  <Button className="approval-decline" aria-label={`Decline ${a.summary}`} disabled={busy === a.id}
                    onClick={() => act(a, "decline")}>
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
