import { useState, type FormEvent } from "react";
import { api, type Profile } from "../api";
import { Button } from "./ui";
const BLANK: Profile = {
  first_name: "", last_name: "", title: "mr", gender: "m", born_on: "", email: "", phone: "+91",
  address: "", city: "", state: "", pincode: "", country: "India",
};
// Your checkout details, typed once. Flights are held in this name; shop and hotel cards show the rest.
export default function ProfileForm({ saved, email, onSaved }: { saved: Profile | null; email: string; onSaved: (p: Profile) => void }) {
  const [p, setP] = useState<Profile>(saved ?? { ...BLANK, email });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const field = (key: keyof Profile, label: string, props: Record<string, unknown> = {}) => (
    <label>
      {label}
      <input value={p[key]} onChange={(e) => setP({ ...p, [key]: e.target.value })} {...props} />
    </label>
  );
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSaved((await api.saveProfile(p)).profile ?? p);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="profile-form" onSubmit={save}>
      <p>
        Orbit fills these in for you: flights are held in your name, and shop and hotel cards take you to the store's
        checkout with your details ready to copy. You review and pay there. Kept encrypted; Delete my data removes them.
      </p>
      <div className="profile-grid">
        {field("first_name", "First name", { required: true, maxLength: 60, autoComplete: "given-name" })}
        {field("last_name", "Last name", { required: true, maxLength: 60, autoComplete: "family-name" })}
        <label>
          Title
          <select value={p.title} onChange={(e) => setP({ ...p, title: e.target.value })}>
            {["mr", "ms", "mrs", "miss", "dr"].map((t) => (
              <option key={t} value={t}>{t[0].toUpperCase() + t.slice(1)}</option>
            ))}
          </select>
        </label>
        <label>
          Gender (as on your ID)
          <select value={p.gender} onChange={(e) => setP({ ...p, gender: e.target.value })}>
            <option value="m">Male</option>
            <option value="f">Female</option>
          </select>
        </label>
        {field("born_on", "Date of birth", { type: "date", required: true, autoComplete: "bday" })}
        {field("phone", "Phone (with country code)", { type: "tel", required: true, pattern: "\\+[1-9][0-9]{7,14}", autoComplete: "tel", title: "Like +919876543210" })}
        {field("email", "Email", { type: "email", required: true, autoComplete: "email" })}
        {field("address", "Address", { maxLength: 200, autoComplete: "street-address" })}
        {field("city", "City", { maxLength: 60, autoComplete: "address-level2" })}
        {field("state", "State", { maxLength: 60, autoComplete: "address-level1" })}
        {field("pincode", "PIN code", { maxLength: 10, autoComplete: "postal-code" })}
        {field("country", "Country", { maxLength: 60, autoComplete: "country-name" })}
      </div>
      {error && <p className="approval-error" role="alert">{error}</p>}
      <Button tone="forest" type="submit" disabled={busy}>
        {busy ? "Saving…" : "Save my details"}
      </Button>
    </form>
  );
}
