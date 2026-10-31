import { useEffect, useRef, useState } from "react";
import { TriangleAlert } from "lucide-react";
import { api } from "../api";
import { Button, Modal } from "./ui";
const HOLD_MS = 2500;
// Delete my data: a loud warning, and a button you hold down for 2.5 s (mouse, touch, or Space / Enter), so a stray
// click or tap can't wipe an account.
export default function DeleteMe({ onClose, onDeleted }: { onClose: () => void; onDeleted: () => void }) {
  const [holding, setHolding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const remove = async () => {
    setHolding(false);
    setBusy(true);
    try {
      await api.deleteMe();
      onDeleted();
    } catch (e) {
      setError(`Couldn't delete your data: ${(e as Error).message}`);
      setBusy(false);
    }
  };
  const start = () => {
    if (busy || holding) return;
    setError("");
    setHolding(true);
    timer.current = window.setTimeout(remove, HOLD_MS);
  };
  const stop = () => {
    window.clearTimeout(timer.current);
    if (!busy) setHolding(false);
  };
  const hold = (key: string) => key === " " || key === "Enter";
  return (
    <Modal title="DELETE EVERYTHING?" label="delete_my_data" onClose={busy ? () => undefined : onClose}>
      <div className="delete-me">
        <p className="delete-warning">
          <TriangleAlert size={28} aria-hidden />
          <strong>This can't be undone.</strong>
        </p>
        <p>
          Your Orbit account goes, with your conversations, booking cards, bank statement, saved details and Google
          connection, and you're signed out. Bookings already confirmed stay with the airline, hotel or store.
        </p>
        {error && <p className="approval-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <Button onClick={onClose} disabled={busy}>
            Keep my account
          </Button>
          <button
            type="button"
            className={`delete-hold${holding ? " holding" : ""}`}
            style={{ ["--hold" as string]: `${HOLD_MS}ms` }}
            disabled={busy}
            aria-label="Delete my data: press and hold to confirm"
            onPointerDown={start}
            onPointerUp={stop}
            onPointerLeave={stop}
            onPointerCancel={stop}
            onContextMenu={(e) => e.preventDefault()}
            onKeyDown={(e) => {
              if (hold(e.key)) {
                e.preventDefault();
                if (!e.repeat) start();
              }
            }}
            onKeyUp={(e) => hold(e.key) && stop()}
            onBlur={stop}
          >
            <span className="delete-hold-fill" aria-hidden />
            <span className="delete-hold-label">
              {busy ? "Deleting…" : holding ? "Keep holding…" : "Hold to delete"}
            </span>
          </button>
        </div>
      </div>
    </Modal>
  );
}
