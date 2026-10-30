import { useEffect, useState, type FormEvent } from "react";
import { MessageCircle } from "lucide-react";
import { api } from "../api";
import { Button } from "./ui";
// Your number for booking alerts (WhatsApp, or SMS): one message when a booking is confirmed or cancelled.
// Shown only once the backend has Twilio set up; the number is kept with your account.
export default function PhoneAlerts() {
  const [channel, setChannel] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [phone, setPhone] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    api.phone().then((p) => {
      setChannel(p.alerts);
      setSaved(p.phone);
      setPhone(p.phone ?? "");
    }, () => undefined);
  }, []);
  if (!channel) return null;
  const save = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const p = await api.setPhone(phone);
      setSaved(p.phone);
      setPhone(p.phone ?? "");
      setNote(p.phone ? "Saved. You'll get a message for each booking you confirm or cancel." : "Removed: no more alerts.");
    } catch (err) {
      setNote((err as Error).message);
    }
  };
  const name = channel === "sms" ? "SMS" : "WhatsApp";
  return (
    <form className="phone-alerts" onSubmit={save}>
      <label>
        <span>
          <MessageCircle size={16} aria-hidden /> {name} alerts for your bookings
        </span>
        <input type="tel" autoComplete="tel" placeholder="+91 98450 12345" value={phone} onChange={(e) => setPhone(e.target.value)} />
      </label>
      <Button type="submit" tone="forest" className="button-outline">
        {saved && phone === saved ? "Saved" : "Save"}
      </Button>
      {note && <p className="phone-alerts-note">{note}</p>}
    </form>
  );
}
