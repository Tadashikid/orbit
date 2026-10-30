import { AnimatedAmount } from "./ui";
import { motion } from "framer-motion";
import {
  useMotionPreferences,
  revealEase,
} from "../hooks/useMotionPreferences";
export default function SpendingChart({
  categories,
}: {
  categories: Record<string, number>;
}) {
  const { reduced } = useMotionPreferences();
  const entries = Object.entries(categories).sort((a, b) => b[1] - a[1]);
  if (!entries.length)
    return (
      <div className="empty-chart">
        <div className="empty-bars">
          <i />
          <i />
          <i />
        </div>
        <p>Category breakdown unavailable.</p>
        <small>
          The categorized Manu CSV wasn’t supplied. Import your statement to see
          the bars.
        </small>
      </div>
    );
  const max = entries[0][1];
  return (
    <div className="spending-chart">
      {entries.map(([name, n], i) => (
        <div key={name}>
          <div className="bar-label">
            <span>{name}</span>
            <strong>
              <AnimatedAmount value={n} />
            </strong>
          </div>
          <div className="bar-track">
            <motion.div
              className={i === 0 ? "orange" : "lime"}
              style={{ width: `${max > 0 ? (n / max) * 100 : 0}%` }}
              initial={reduced ? false : { scaleX: 0 }}
              whileInView={{ scaleX: 1 }}
              viewport={{ once: true }}
              transition={{ duration: reduced ? 0 : 0.8, ease: revealEase }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
