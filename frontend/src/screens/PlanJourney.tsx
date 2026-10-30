import {
  BedDouble,
  Plane,
  MapPin,
  CalendarDays,
  Wallet,
  Utensils,
  Bus,
  Ticket,
  Info,
  Check,
  ShieldCheck,
  Tag,
  Star,
  Users,
} from "lucide-react";
import { motion, useAnimationControls } from "framer-motion";
import { useEffect, useRef } from "react";
import { useMotionPreferences } from "../hooks/useMotionPreferences";
import type { Part, Server, StatementInfo, Verdict } from "../types";
import { AnimatedAmount, Button, money, shortDate } from "../components/ui";
// One flashcard per part of the cost the engine priced (backend/engine.py: numbers.breakdown).
const CARDS = {
  flight: {
    label: "Flights",
    headline: "FIRST, GETTING THERE.",
    step: "JOURNEY",
    copy: "A short getaway starts with a flight that fits your plans.",
    budget: "flight",
    Icon: Plane,
  },
  stay: {
    label: "Your stay",
    headline: "THEN, A PLACE TO UNWIND.",
    step: "STAY",
    copy: "Leave room in your budget for somewhere comfortable to stay.",
    budget: "stay",
    Icon: BedDouble,
  },
  other: {
    label: "Other costs",
    headline: "AND THE LITTLE THINGS.",
    step: "EXTRAS",
    copy: "Food, local travel, and a little room for the unexpected.",
    budget: "other-cost",
    Icon: Wallet,
  },
  product: {
    label: "The item",
    headline: "FIRST, WHAT IT COSTS.",
    step: "ITEM",
    copy: "New, from stores you’d actually buy from.",
    budget: "item",
    Icon: Tag,
  },
  outing: {
    label: "Your plans",
    headline: "FIRST, THE NIGHT ITSELF.",
    step: "PLAN",
    copy: "What an evening like this usually costs, for everyone going.",
    budget: "outing",
    Icon: Ticket,
  },
} as const;
const CITY: Record<string, string> = { BLR: "Bengaluru" };
// Where a card's amount came from, said plainly on its tab.
const tag = (p: Part) =>
  p.low == null
    ? "NOT PRICED YET"
    : ({ live: "LIVE PRICES", cached: "SAVED PRICES", seeded: "SAMPLE PRICES", user: "YOUR PRICE" } as Record<string, string>)[
        p.source ?? ""
      ] ?? "BUDGET ESTIMATE";
const day = (iso?: string | null) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" }) : "";
const CAPTIONS: Record<Verdict["verdict"], string> = {
  yes: "THIS FITS YOUR BUDGET",
  yes_with_conditions: "THIS COULD WORK, WITH A FEW CONDITIONS",
  risky: "POSSIBLE, BUT IT’S TIGHT",
  no: "YOUR BUDGET NEEDS A LITTLE MORE ROOM",
  insufficient_data: "A LITTLE MORE INFORMATION IS NEEDED",
  info: "HERE’S WHAT WE FOUND",
};
function title(v: Verdict | null) {
  const i = v?.intent;
  if (!v || !i) return "YOUR PLAN, TAKING SHAPE.";
  if (v.kind === "trip") {
    const nights = i.start && i.end ? Math.round((Date.parse(i.end) - Date.parse(i.start)) / 86400000) : 1;
    const weekend = nights <= 2 && i.start && new Date(`${i.start}T00:00:00`).getDay() === 6;
    return `${weekend ? "A WEEKEND" : `${nights + 1} DAYS`} IN ${(i.city || "YOUR TRIP").toUpperCase()}.`;
  }
  if (v.kind === "savings_goal") return `SAVING FOR ${(i.item || "IT").toUpperCase()}.`;
  if (v.kind === "expense") return `${(i.item || "A NIGHT OUT").toUpperCase()}.`;
  return `A NEW ${(i.item || "ITEM").toUpperCase()}.`;
}
function Details({ part, verdict, servers }: { part: Part; verdict: Verdict; servers: Server[] }) {
  const i = verdict.intent;
  const travelOn = servers.some((s) => s.id === "travel" && s.status === "connected");
  if (part.key === "flight") {
    const [out, back] = part.legs ?? [];
    return (
      <>
        <div className="route-display">
          <div>
            <strong>{i?.origin}</strong>
            <span>{CITY[i?.origin ?? ""] ?? i?.origin}</span>
          </div>
          <span className="route-line">
            <Plane size={22} />
          </span>
          <div>
            <strong>{i?.dest ?? "—"}</strong>
            <span>{i?.city}</span>
          </div>
        </div>
        <div className="travel-facts">
          <span>
            <CalendarDays size={17} />
            {day(i?.start)}
            {i?.end ? ` – ${day(i.end)}` : ""}
          </span>
          {out && (
            <span>
              <Plane size={17} />
              Out {out.depart} {out.airline} · {money(out.price)}
              {out.stops ? ` · ${out.stops} stop${out.stops > 1 ? "s" : ""}` : ""}
            </span>
          )}
          {back && (
            <span>
              <Plane size={17} />
              Back {back.depart} {back.airline} · {money(back.price)}
              {back.stops ? ` · ${back.stops} stop${back.stops > 1 ? "s" : ""}` : ""}
            </span>
          )}
        </div>
        <div className="detail-note flight-notice surface-forest">
          <Info size={17} />
          <p>
            {out
              ? "The cheapest fares we found for these dates. Confirm the fare before booking."
              : travelOn
                ? "No fares found for these dates yet."
                : "Flight details haven’t been read. Switch Flights on to price the trip."}
          </p>
        </div>
      </>
    );
  }
  if (part.key === "stay") {
    const nights = part.nights ?? 1;
    return (
      <>
        <div className="stay-heading">
          <BedDouble size={36} />
          <strong>
            A PLACE TO CALL YOURS.
            <br />
            {nights <= 2 ? "JUST FOR THE WEEKEND." : `FOR ${nights} NIGHTS.`}
          </strong>
        </div>
        <div className="travel-facts">
          <span>
            <MapPin size={17} />
            {i?.city}
          </span>
          {part.hotel ? (
            <span>
              <Star size={17} />
              e.g. {part.hotel.name} · {money(part.hotel.per_night)} a night
              {part.hotel.rating ? ` · rated ${part.hotel.rating}` : ""}
            </span>
          ) : (
            <span>
              <Check size={17} />
              You choose where to stay
            </span>
          )}
        </div>
        <div className="detail-note">
          <Info size={17} />
          <p>
            {part.per_night
              ? `Typical 2–4 star hotels for these dates: ${money(part.per_night[0])} to ${money(part.per_night[1])} a night, hostels left out. Nothing is booked.`
              : part.low != null
                ? "No hotel prices for these dates, so this is your cost estimate per night."
                : "Not priced yet. Connect your budget to include an estimate."}
          </p>
        </div>
      </>
    );
  }
  if (part.key === "other")
    return (
      <>
        <div className="other-cost-items">
          {[
            { Icon: Utensils, label: "Meals & coffee" },
            { Icon: Bus, label: "Getting around" },
            { Icon: Ticket, label: "Things to do" },
          ].map((item) => (
            <div key={item.label}>
              <item.Icon size={23} />
              <span>{item.label}</span>
              <span>Included in allowance</span>
            </div>
          ))}
        </div>
        <div className="detail-note">
          <ShieldCheck size={17} />
          <p>
            {part.low != null
              ? `Food and local transport for ${part.days} days, from your cost estimates. An allowance, not a list of purchases.`
              : "Not priced yet. Connect your budget to include your cost estimates."}
          </p>
        </div>
      </>
    );
  if (part.key === "product")
    return (
      <>
        <div className="other-cost-items">
          {(part.offers ?? []).map((o, n) => (
            <div key={`${n}-${o.store}`}>
              <Tag size={23} />
              <span>
                {o.store} · {money(o.price)}
                {o.mrp ? ` (MRP ${money(o.mrp)})` : ""}
              </span>
              <span>{o.title}{o.rating ? ` · Rated ${o.rating}${o.reviews ? ` · ${o.reviews} reviews` : ""}` : ""}</span>
            </div>
          ))}
        </div>
        <div className="detail-note">
          <ShieldCheck size={17} />
          <p>
            {part.source === "user"
              ? "The price you gave."
              : part.offers?.length
                ? part.note
                  ? `${part.note}. New, from mainstream stores only.`
                  : "New, from mainstream stores only. Refurbished, accessories, other models and odd prices left out."
                : "We couldn’t confirm a price at mainstream stores. Name the exact model, or tell us the price."}
          </p>
        </div>
      </>
    );
  return (
    <>
      <div className="travel-facts">
        <span>
          <Users size={17} />
          {part.people ?? 1} {part.people === 1 ? "person" : "people"}
        </span>
        <span>
          <CalendarDays size={17} />
          {day(i?.start)}
        </span>
        {part.per_person && (
          <span>
            <Wallet size={17} />
            {money(part.per_person[0])} to {money(part.per_person[1])} per person
          </span>
        )}
      </div>
      <div className="detail-note">
        <Info size={17} />
        <p>
          {part.low != null
            ? "From your cost estimates for an evening like this. Confirm the menu before you go."
            : "Not priced yet. Connect your budget to include your cost estimates."}
        </p>
      </div>
    </>
  );
}
export default function PlanJourney({
  verdict,
  previous,
  servers,
  statement,
  today,
  busy,
  onConnect,
  onSetup,
  onBalance,
  onInsights,
}: {
  verdict: Verdict | null;
  previous: Verdict | null;
  servers: Server[];
  statement: StatementInfo | null;
  today: string;
  busy: boolean;
  onConnect: () => void;
  onSetup: () => void;
  onBalance: () => void;
  onInsights: () => void;
}) {
  const { reduced } = useMotionPreferences();
  const settle = useAnimationControls();
  const budgetRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const card = budgetRef.current;
    if (!card) return;
    if (busy || reduced) {
      settle.stop();
      settle.set({ scale: 1 });
      return;
    }
    card.dataset.settling = "true";
    settle.set({ scale: 1.04 });
    void settle.start({
      scale: 1,
      transition: { type: "spring", duration: 0.24, bounce: 0.12 },
    });
    const timer = setTimeout(() => {
      delete card.dataset.settling;
    }, 900);
    return () => {
      clearTimeout(timer);
      settle.stop();
      delete card.dataset.settling;
    };
  }, [busy, verdict?.headline, reduced, settle]);
  const finance = servers.find((s) => s.id === "finance");
  const financeOn = finance?.status === "connected";
  // No breakdown: a general question, or nothing could be priced. The answer stands on its own.
  if (verdict && !busy && !verdict.numbers.breakdown?.length)
    return (
      <section className="other-decision" id="plan">
        <span className="journey-kicker">YOUR ANSWER</span>
        <h2>{verdict.headline}</h2>
        <p>
          {verdict.explanation ??
            (verdict.verdict === "info"
              ? "Ask about a trip, a purchase, a night out or a savings goal to see what fits."
              : "We need a price and the relevant details before we can check this decision.")}
        </p>
        {verdict.verdict === "insufficient_data" && !financeOn && (
          <Button tone="forest" onClick={onConnect}>
            Add your budget
          </Button>
        )}
        <button className="text-button" onClick={onInsights}>
          View detailed insights
        </button>
      </section>
    );
  // While the first answer is on its way there's no breakdown yet: show the trip's three cards, loading.
  const parts: Part[] = verdict?.numbers.breakdown?.length
    ? verdict.numbers.breakdown
    : (["flight", "stay", "other"] as const).map((key) => ({ key, low: null, high: null }));
  const hasFinance = verdict?.numbers.balance != null;
  const cost = verdict?.numbers.trip_cost;
  const priced = parts.filter((p) => p.low != null);
  const live = priced.some((p) => ["live", "cached"].includes(p.source ?? ""));
  const stale =
    hasFinance && statement && today && (Date.parse(today) - Date.parse(statement.as_of)) / 86400000 > 7;
  return (
    <section className="plan-journey" id="plan" aria-label="Your plan">
      <div className="journey-intro">
        <div>
          <span className="journey-kicker">YOUR PLAN, ONE PART AT A TIME</span>
          <h2>{title(verdict)}</h2>
          <p>
            {verdict?.kind === "trip" || !verdict
              ? "Getting there. Staying there. Making it all add up."
              : "What it costs, and whether it fits."}
          </p>
        </div>
        <span className="journey-scroll-note">SCROLL TO EXPLORE</span>
      </div>
      <p className="estimate-disclosure">
        <Info size={16} />
        {live
          ? "Real prices where we found them, your estimates elsewhere. Nothing is booked or bought."
          : "Estimates to help you plan, not confirmed bookings or prices."}
      </p>
      <div className="flashcard-stack">
        {parts.map((part, i) => {
          const k = CARDS[part.key];
          const next = parts[i + 1] ? CARDS[parts[i + 1].key] : null;
          const surface = i === 1 ? "surface-paper" : "surface-forest";
          return (
            <motion.article
              className={`journey-card journey-${part.key} ${surface}`}
              initial={false}
              key={part.key}
              style={{ "--card-index": i } as React.CSSProperties}
              aria-labelledby={`journey-${part.key}`}
            >
              <div className={`flashcard-tab ${surface}`}>
                <span>0{i + 1}</span>
                <k.Icon size={19} />
                <strong>{k.label}</strong>
                <span className="tab-budget-label">{tag(part)}</span>
              </div>
              <div className="flashcard-body">
                <div className="flashcard-copy">
                  <span className="card-step">THE {k.step}</span>
                  <h3 id={`journey-${part.key}`}>{k.headline}</h3>
                  <p>{k.copy}</p>
                  <div className="card-budget">
                    <span>Your {k.budget} budget</span>
                    <strong>
                      {part.low != null && part.high != null ? (
                        <>
                          <AnimatedAmount value={part.low} />
                          <span>–</span>
                          <AnimatedAmount value={part.high} />
                        </>
                      ) : (
                        "Not priced yet"
                      )}
                    </strong>
                  </div>
                </div>
                <div className={`flashcard-details ${surface}`}>
                  {busy || !verdict ? (
                    <div className="calm-loading" role="status">
                      <div />
                      <div />
                      <div />
                      <span>Putting your plan together…</span>
                    </div>
                  ) : (
                    <Details part={part} verdict={verdict} servers={servers} />
                  )}
                </div>
              </div>
              <footer className="flashcard-footer">
                <span>
                  0{i + 1} / 0{parts.length}
                </span>
                <span>{next ? `NEXT UP: ${next.label.toUpperCase()}` : "NEXT UP: THE WHOLE PICTURE"}</span>
              </footer>
            </motion.article>
          );
        })}
      </div>
      <section
        className="trip-summary surface-forest"
        id="summary"
        aria-labelledby="summary-heading"
      >
        <div className="summary-heading">
          <span className="journey-kicker">THE WHOLE PICTURE</span>
          <h2 id="summary-heading">ALL TOGETHER NOW.</h2>
          <p>Everything you need to decide, in one place.</p>
        </div>
        <div className="summary-layout">
          <div className="summary-costs">
            {parts.map((part) => {
              const k = CARDS[part.key];
              return (
                <div key={part.key}>
                  <k.Icon size={21} />
                  <span>{k.label}</span>
                  <strong>
                    {part.low != null && part.high != null ? (
                      <>
                        <AnimatedAmount value={part.low} /> – <AnimatedAmount value={part.high} />
                      </>
                    ) : (
                      "Not priced yet"
                    )}
                  </strong>
                </div>
              );
            })}
            <div className="summary-total">
              <span>{verdict?.kind === "trip" || !verdict ? "Total trip estimate" : "Total estimate"}</span>
              <strong>
                {cost?.low != null && cost.high != null ? (
                  <>
                    <AnimatedAmount value={cost.low} />
                    <span> – </span>
                    <AnimatedAmount value={cost.high} />
                  </>
                ) : (
                  "Not priced yet"
                )}
              </strong>
            </div>
          </div>
          <motion.div
            className="summary-decision surface-forest"
            ref={budgetRef}
            initial={false}
            animate={settle}
          >
            {busy ? (
              <div className="calm-loading">
                <div />
                <div />
                <span>Checking what fits…</span>
              </div>
            ) : hasFinance && verdict ? (
              <>
                <span className="decision-caption">{CAPTIONS[verdict.verdict]}</span>
                <h3 aria-live="polite">{verdict.headline}</h3>
                {verdict.explanation && <p>{verdict.explanation}</p>}
                {previous && previous.question === verdict.question && previous.verdict !== verdict.verdict && (
                  <p className="answer-change">
                    Your answer changed after adding more information.
                  </p>
                )}
                <div className="summary-money">
                  <span>
                    Balance{" "}
                    <strong>
                      <AnimatedAmount value={verdict.numbers.balance ?? 0} />
                    </strong>
                  </span>
                  <span>
                    Monthly commitments{" "}
                    <strong>
                      ≈ <AnimatedAmount value={verdict.numbers.monthly_commitments ?? 0} />
                    </strong>
                  </span>
                  {verdict.numbers.remaining.low != null && verdict.numbers.remaining.high != null && (
                    <span>
                      Left before payday{" "}
                      <strong>
                        <AnimatedAmount value={verdict.numbers.remaining.low} /> to{" "}
                        <AnimatedAmount value={verdict.numbers.remaining.high} />
                      </strong>
                    </span>
                  )}
                </div>
              </>
            ) : (
              <>
                <span className="decision-caption">ONE MORE PIECE OF THE PICTURE</span>
                <h3>
                  DOES IT FIT
                  <br />
                  YOUR BUDGET?
                </h3>
                <p>
                  {verdict?.headline ??
                    "We can check your dates, but we need your budget to check affordability."}
                </p>
                <Button tone="forest" onClick={financeOn ? onSetup : onConnect}>
                  {financeOn ? "Add your statement" : "Add your budget"}
                </Button>
              </>
            )}
          </motion.div>
        </div>
        <div className="summary-actions">
          <button className="insights-link" onClick={onInsights}>
            View detailed insights <Info size={17} />
          </button>
        </div>
        {stale && statement && (
          <p className="balance-freshness">
            Your balance is from {shortDate(statement.as_of)}.{" "}
            <button onClick={onBalance}>Upload a newer statement before deciding</button>
          </p>
        )}
        <p className="summary-smallprint">
          An estimate to help you decide. Confirm prices and commitments before
          spending.
        </p>
      </section>
    </section>
  );
}
