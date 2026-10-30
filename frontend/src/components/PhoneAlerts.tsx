import { useEffect, useState, type FormEvent } from "react";
import QRCode from "qrcode";
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
  const [join, setJoin] = useState<{ link: string; qr: string } | null>(null);
  useEffect(() => {
    api.phone().then((p) => {
      setChannel(p.alerts);
      setSaved(p.phone);
      setPhone(p.phone ?? "");
      // The sandbox only messages phones that joined it: scanning this opens WhatsApp with the join message typed in.
      if (p.join?.startsWith("https://wa.me/"))
        QRCode.toDataURL(p.join, { margin: 1, width: 160 }).then((qr) => setJoin({ link: p.join!, qr }), () => undefined);
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
      {join && (
        <div className="phone-alerts-join">
          <img src={join.qr} width={120} height={120} alt="QR code: opens WhatsApp to join Orbit's alerts" />
          <p>
            <strong>First time?</strong> Scan with your phone camera, then press Send in WhatsApp. That lets Orbit
            message you (test mode: send it again after 24 hours of quiet). On this phone?{" "}
            <a href={join.link} target="_blank" rel="noopener noreferrer">
              Open WhatsApp
            </a>
          </p>
        </div>
      )}
    </form>
  );
}
