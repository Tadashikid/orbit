import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { Send } from "lucide-react";
import { api } from "../api";
import { Button } from "./ui";
// Telegram booking alerts for anyone: scan the QR, tap Start, and that chat gets every confirmed / cancelled booking.
// Shown only once the backend has a bot token. While a QR is up, it checks every 2 s for whoever just tapped Start.
export default function TelegramAlerts() {
  const [status, setStatus] = useState<{ ready: boolean; chats: number } | null>(null);
  const [join, setJoin] = useState<{ link: string; qr: string; chats: number } | null>(null);
  const [note, setNote] = useState("");
  useEffect(() => {
    api.telegram().then(setStatus, () => undefined);
  }, []);
  useEffect(() => {
    if (!join) return;
    const stop = setTimeout(() => setJoin(null), 10 * 60_000); // the one-time link expires after 10 minutes
    const poll = setInterval(async () => {
      const s = await api.telegram().catch(() => null);
      if (s && s.chats > join.chats) {
        setStatus(s);
        setJoin(null);
        setNote("Linked. That chat will get a message for each booking you confirm or cancel.");
      }
    }, 2000);
    return () => {
      clearTimeout(stop);
      clearInterval(poll);
    };
  }, [join]);
  if (!status?.ready) return null;
  const show = async () => {
    try {
      const { link } = await api.telegramLink();
      if (!link.startsWith("https://t.me/")) return;
      setJoin({ link, qr: await QRCode.toDataURL(link, { margin: 1, width: 160 }), chats: status.chats });
      setNote("");
    } catch (err) {
      setNote((err as Error).message);
    }
  };
  const stop = async () => {
    setStatus(await api.telegramUnlink());
    setNote("Telegram alerts stopped for every linked chat.");
  };
  return (
    <div className="phone-alerts">
      <span className="phone-alerts-title">
        <Send size={16} aria-hidden /> Telegram alerts for your bookings
        {status.chats > 0 && ` · ${status.chats} chat${status.chats > 1 ? "s" : ""} linked`}
      </span>
      <Button type="button" tone="forest" className="button-outline" onClick={show}>
        {status.chats ? "Add another phone" : "Get alerts on Telegram"}
      </Button>
      {status.chats > 0 && (
        <Button type="button" tone="forest" className="button-outline" onClick={stop}>
          Stop Telegram alerts
        </Button>
      )}
      {join && (
        <div className="phone-alerts-join">
          <img src={join.qr} width={120} height={120} alt="QR code: opens Orbit's Telegram bot to link this phone" />
          <p>
            Scan with your phone camera, then tap <strong>Start</strong> in Telegram. Works for anyone, once (this code
            expires in 10 minutes). On this phone?{" "}
            <a href={join.link} target="_blank" rel="noopener noreferrer">
              Open Telegram
            </a>
          </p>
        </div>
      )}
      {note && <p className="phone-alerts-note">{note}</p>}
    </div>
  );
}
