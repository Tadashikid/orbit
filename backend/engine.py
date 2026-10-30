"""Deterministic decision engine: tool results -> the verdict JSON (see contracts/).

No LLM and no I/O: every number comes from a tool result.

The money rule is a cash-flow projection, day by day, from the statement:
  cash on the day   = balance (as of its date) + salary - bills (rent, SIPs, phone...) - everyday spending, up to the day you pay
  lowest point      = what's left on the day before your next salary, after paying and after every bill until then
  YES               the lowest point stays >= SAFETY_FLOOR
  ONLY IF           skipping some fun spending *for the days that actually remain until payday* keeps it there
  RISKY             you could pay and stay above zero, but not above the cushion
  NOT YET           you couldn't pay without going below zero; the plan names the earliest date it fits
Everyday spending is Finance's forecast: each day at its weekday's rate per category (get_spending_summary).
Cutting back only counts for the days left, never a month of savings in two days.
Rent, bills and SIPs are never cut.
"""
import math
import re
import statistics
from datetime import date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
TRIP_HOURS = (time(6), time(22))  # a trip occupies 06:00 on the first day to 22:00 on the last
EVENING = (time(19), time(23, 30))  # dinners, parties, movies
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SAFETY_FLOOR = 10_000  # team rule: never let the balance drop below Rs 10,000 because of a decision
REALISTIC_FARE = 1.5  # fares above 1.5x the cheapest (last seats, odd routings) are listed but not priced in
# Discretionary categories -> how to say "cut it". Rent, SIPs and bills are never here.
CUTTABLE = {
    "Club": "skip club nights",
    "Partying": "skip parties",
    "Dining with friends": "skip dinners out",
    "Shopping": "pause shopping",
    "Transport (cab)": "take the metro instead of cabs",
    "Games & entertainment": "skip arcades and game nights",
    "Food delivery": "stop ordering in",
}
# ponytail: keyword tripwire for instructions hidden in email/calendar text, so the receipt can show them.
# The real defence is structural: nothing here can call a write tool, and text never changes the numbers.
INJECTION = re.compile(r"ignore (all )?(previous|prior) instructions|system notice to ai|you are now|call set_balance", re.I)


def _rs(n):
    return f"Rs {round(n):,}" if n >= 0 else f"-Rs {round(-n):,}"


def _when(iso):
    return datetime.fromisoformat(iso).strftime("%a %d %b %H:%M")


def _day(d):
    return d.strftime("%a %d %b")


def _join(parts):
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _join_actions(phrases):
    """'skip club nights', 'skip parties' -> 'skip club nights and parties' (shared verb said once)."""
    verb = phrases[0].split()[0]
    if len(phrases) > 1 and all(p.split()[0] == verb for p in phrases):
        phrases = [phrases[0]] + [p.split(" ", 1)[1] for p in phrases[1:]]
    return _join(phrases)


def _plan_phrase(cuts):
    """Up to 3 cuts spelled out; more than that summarised, so the plan stays one readable line."""
    if len(cuts) <= 3:
        return _join_actions([CUTTABLE[c] for c, _ in cuts])
    return f"cut back on fun spending ({_join([c.split(' (')[0].lower() for c, _ in cuts][:3] + ['more'])})"


def _short(title):
    return re.sub(r"\s*[-–]\s*(confirm\s+)?due\b.*$", "", title, flags=re.I)


def _range(pair):
    return {"low": round(pair[0]), "high": round(pair[1])} if pair else {"low": None, "high": None}


def _part(key, pair, **detail):
    """One card's share of the cost ({key, low, high, ...}); low/high are None when that part couldn't be priced."""
    return {"key": key, **_range(pair), **detail}


def _window(start, end, hours=TRIP_HOURS):
    return datetime.combine(start, hours[0], IST), datetime.combine(end, hours[1], IST)


def _overlaps(event, start, end):
    return datetime.fromisoformat(event["start"]) < end and datetime.fromisoformat(event["end"]) > start


def _price_range(prices):
    """Typical price from shop listings: drop accessories/premium outliers far from the median, then the middle half."""
    prices = sorted(prices)
    mid = statistics.median(prices)
    prices = [p for p in prices if 0.4 * mid <= p <= 2.5 * mid]
    if len(prices) >= 4:
        q1, _, q3 = statistics.quantiles(prices, n=4)
        return q1, q3
    return prices[0], prices[-1]


def _spend(rates, start, end, cats):
    """Forecast everyday spending on `cats` after `start` up to and including `end`: each day at its weekday's rate
    (Finance's model: a Sunday with club night costs far more than a Tuesday)."""
    return sum(rates[c][(start + timedelta(days=i)).weekday()] for i in range(1, (end - start).days + 1) for c in cats)


def _flow(start, end, recurring, rates, skip=()):
    """Money change after `start` up to and including `end`: recurring salary in, recurring bills out,
    and the everyday spending forecast for each day (minus the skipped categories)."""
    if end <= start:
        return 0
    total = -_spend(rates, start, end, [c for c in rates if c not in skip])
    d = start + timedelta(days=1)
    while d <= end:
        total += sum(r["amount"] if r["type"] == "income" else -r["amount"] for r in recurring if r["day_of_month"] == d.day)
        d += timedelta(days=1)
    return total


def _math(balance, as_of, cut_from, low_day, recurring, rates, skip, cost, thing):
    """The lowest point before payday as a receipt: rows that add up, to the rupee, to the number on the card."""
    rows, days = [{"label": f"Balance (as of {_day(as_of)})", "amount": balance}], (low_day - as_of).days
    ins, outs, d = [], 0, as_of + timedelta(days=1)
    while d <= low_day:
        for r in (r for r in recurring if r["day_of_month"] == d.day):
            if r["type"] == "income":
                ins.append({"label": f"Salary ({_day(d)})", "amount": r["amount"]})
            else:
                outs += r["amount"]
        d += timedelta(days=1)
    rows += ins
    if outs:
        rows.append({"label": f"Rent, bills & SIPs due {_day(as_of + timedelta(days=1))} - {_day(low_day)}", "amount": -outs})
    if days:
        rows.append({"label": f"Everyday spending forecast, {days} days ({_day(as_of + timedelta(days=1))} - {_day(low_day)})",
                     "amount": -_spend(rates, as_of, low_day, rates)})
    left = (low_day - cut_from).days
    saved = _spend(rates, cut_from, low_day, [c for c in skip if c in rates])
    if left and saved:  # one row for the whole plan: "Skip club nights and parties, the 23 days left"
        phrase = _plan_phrase([(c, 0) for c in skip])
        rows.append({"label": f"{phrase[0].upper()}{phrase[1:]}, the {left} days left", "amount": saved})
    span = f" (top of {_rs(cost[0])} - {_rs(cost[1])})" if cost[0] != cost[1] else ""
    rows.append({"label": f"{thing[0].upper()}{thing[1:]}{span}", "amount": -cost[1]})
    rows.append({"label": f"Left on {_day(low_day)}, the day before payday", "amount": sum(r["amount"] for r in rows)})
    return rows


def _next_salary(after, recurring):
    days = {r["day_of_month"] for r in recurring if r["type"] == "income"}
    for i in range(1, 63):
        if (after + timedelta(days=i)).day in days:
            return after + timedelta(days=i)
    return after + timedelta(days=31)  # ponytail: no recurring income in the statement -> assume a monthly cycle


def decide(question, intent, results, known_servers):
    """intent from planner.validate/parse, results from registry.call, known_servers = every server Orbit knows."""
    kind = intent["kind"]
    evidence, tradeoffs, by_tool = [], [], {}
    for r in results:
        if r["ok"]:
            by_tool.setdefault(r["tool"], []).append(r)
        else:
            evidence.append({"server": r["server"], "tool": r["tool"], "finding": f"FAILED: {r['error'][:100]}", "as_of": "", "source": "error"})

    def note(r, finding):
        res = r["result"]
        evidence.append({"server": r["server"], "tool": r["tool"], "finding": finding,
                         "as_of": str(res.get("as_of", "")), "source": res.get("source", "")})

    def first(tool):
        return by_tool[tool][0] if tool in by_tool else None

    extra = {}

    def out(verdict, headline, balance=None, cost=None, commitments=None, remaining=None):
        return {
            "question": question,
            "kind": kind,
            "verdict": verdict,
            "headline": headline,
            "numbers": {
                "balance": None if balance is None else round(balance),
                "trip_cost": _range(cost),  # the cost of whatever was asked about (field name kept from the contract)
                "monthly_commitments": None if commitments is None else round(commitments),
                "remaining": _range(remaining),  # lowest balance before the next salary, after paying + the plan
                "safety_floor": None if balance is None else SAFETY_FLOOR,
                "cash_on_day": extra.get("cash_on_day"),  # estimated cash on the day you pay, before paying
                "pay_day": extra.get("pay_day"),
                "next_salary": extra.get("next_salary"),
                "math": extra.get("math"),  # [{label, amount}], last row = the lowest point (worst case), sums exactly
                "breakdown": extra.get("breakdown"),  # the cost per card: flight/stay/other, product offers, or outing
            },
            "evidence": evidence,
            "tradeoffs": tradeoffs,
            "not_read": sorted(set(known_servers) - {e["server"] for e in evidence if e["source"] != "error"}),
        }

    # --- time: calendar ---
    window = (_window(intent["start"], intent["end"]) if kind == "trip"
              else _window(intent["start"], intent["start"], EVENING) if kind == "expense" else None)
    free = None
    for r in by_tool.get("find_free_slots", []):
        slots = r["result"]["slots"]
        if window:
            free = any(datetime.fromisoformat(s["start"]) <= window[0] and datetime.fromisoformat(s["end"]) >= window[1] for s in slots)
            note(r, f"{_day(intent['start'])} - {_day(intent['end'] or intent['start'])} {'fully free' if free else 'not fully free'}")
        else:
            note(r, f"{len(slots)} free slots")
    for r in by_tool.get("list_events", []):
        events = r["result"]["events"]
        clashes = [e for e in events if window and _overlaps(e, *window)]
        when = "during the trip" if kind == "trip" else "that evening"
        note(r, f"{len(events)} events read" + (f"; clash: {_join([e['title'] for e in clashes])}" if clashes else f"; none {when}" if window else ""))
        tradeoffs += [f"Move or skip '{e['title']}' ({_when(e['start'])})" for e in clashes]
        if window:
            free = False if clashes else (True if free is None else free)

    # --- deadlines: email (text is untrusted; flagged emails never become part of the plan) ---
    flagged = set()
    for r in by_tool.get("list_tasks", []):
        tasks = r["result"]["tasks"]
        bad = [t for t in tasks if INJECTION.search(f"{t['title']} {t.get('snippet', '')}")]
        flagged |= {t["title"] for t in bad}
        note(r, f"{len(tasks)} emails with deadlines")
        if bad:
            note(r, f"{len(bad)} email{'s contain' if len(bad) > 1 else ' contains'} instructions aimed at the AI - treated as data, not followed")
    near_end = datetime.combine(intent["end"] + timedelta(days=1), time(23, 59), IST) if kind == "trip" else None
    deadline_tradeoffs = []
    for r in by_tool.get("get_deadlines", []):
        due = [t for t in r["result"]["tasks"] if t["title"] not in flagged and (near_end is None or datetime.fromisoformat(t["deadline"]) <= near_end)]
        note(r, "; ".join(f"{_short(t['title'])} due {_when(t['deadline'])}" for t in due) or "No deadlines around then")
        if kind == "trip":
            deadline_tradeoffs += [f"Before you go: {_short(t['title'])} (due {_when(t['deadline'])})" for t in due]

    # --- flights ---
    legs = {}
    for r in by_tool.get("search_flights", []):
        res = r["result"]
        fares = sorted(res["results"], key=lambda f: f["price"])
        usable = [f for f in fares if f["price"] <= fares[0]["price"] * REALISTIC_FARE] if fares else []
        legs[(res["origin"], res["date"])] = usable
        span = f"{_rs(fares[0]['price'])} - {_rs(fares[-1]['price'])} ({len(fares)} flight{'s' if len(fares) > 1 else ''})" if fares else "no fares found"
        if len(usable) < len(fares):
            span += f"; pricing on the {len(usable)} within 1.5x of the cheapest"
        note(r, f"{res['origin']}-{res['dest']} {_day(date.fromisoformat(res['date']))}: {span}")
    o = b = flights = flight_source = None
    nights = (intent["end"] - intent["start"]).days if kind == "trip" else 0
    if kind == "trip":
        o, b = legs.get((intent["origin"], intent["start"].isoformat())), legs.get((intent["dest"], intent["end"].isoformat()))
        flights = (o[0]["price"] + b[0]["price"], o[-1]["price"] + b[-1]["price"]) if o and b else None
        flight_source = next((r["result"]["source"] for r in by_tool.get("search_flights", [])), None)

    # --- hotels: real room rates for the stay (Travel already left out hostels and vacation rentals) ---
    hotel = None
    for r in by_tool.get("search_hotels", []):
        res = r["result"]
        rated = sorted([h for h in res["results"] if (h.get("rating") or 0) >= 3.8] or res["results"], key=lambda h: h["per_night"])
        if len(rated) >= 3:
            nightly = [h["per_night"] for h in rated]
            per_night = (nightly[len(nightly) // 4], round(statistics.median(nightly)))  # the budget end to the typical room
            pick = next(h for h in rated if h["per_night"] >= per_night[0])
            hotel = {"per_night": per_night, "example": pick, "source": res["source"]}
            stars = f", rated {pick['rating']}" if pick.get("rating") else ""
            note(r, f"{len(rated)} hotels in {res['city']} for {_day(date.fromisoformat(res['check_in']))} - "
                    f"{_day(date.fromisoformat(res['check_out']))}: typical {_rs(per_night[0])} - {_rs(per_night[1])} a night "
                    f"(2-4 star, hostels left out); e.g. {pick['name']} {_rs(pick['per_night'])}{stars}")
        else:
            note(r, f"Only {len(res['results'])} hotel prices for {res['city']}, so the stay uses your cost estimate")

    # --- the user's cost table: the stay (when there are no hotel prices), food, local transport, outings ---
    stay = other = per_person = None
    if r := first("get_cost_table"):
        items = {i["key"]: i for i in r["result"].get("items", [])}
        if kind == "trip":
            kinds = ("stay_per_night", "food_per_day", "local_transport_per_day")
            city = intent["city"].lower()
            fallback = "abroad" if intent.get("abroad") else "default"
            row, days = (lambda k: items.get(f"{city}_{k}") or items.get(f"{fallback}_{k}")), nights + 1
            generic = "" if all(f"{city}_{k}" in items for k in kinds) else f" (default estimates: no {intent['city']}-specific numbers yet)"
            if not hotel and (s := row("stay_per_night")):
                stay = (s["low"] * nights, s["high"] * nights)
            if (food := row("food_per_day")) and (local := row("local_transport_per_day")):
                other = tuple((food[k] + local[k]) * days for k in ("low", "high"))
            told = "; ".join(([f"stay for {nights} night{'s' if nights != 1 else ''} {_rs(stay[0])} - {_rs(stay[1])}"] if stay else [])
                             + ([f"food + local transport for {days} days {_rs(other[0])} - {_rs(other[1])}"] if other else []))
            note(r, told[0].upper() + told[1:] + generic if told else f"No cost estimates for {intent['city']} yet")
        elif kind == "expense" and (row := items.get(f"{intent['expense_type']}_per_person")):
            per_person = (row["low"], row["high"])
            note(r, f"{row.get('label', intent['expense_type'])}: {_rs(row['low'])} - {_rs(row['high'])} per person, x{intent['people']}")
        else:
            note(r, "Cost estimates read")

    # --- shop prices ---
    # Price Check has already removed refurbished, accessories, other models and scams; prices come only from
    # mainstream stores, and only when at least two of them agree (one odd listing is not a market price).
    if hotel:
        stay = tuple(p * nights for p in hotel["per_night"])
    price = best = price_source = price_note = None
    offers = []
    for r in by_tool.get("check_price", []):
        res = r["result"]
        trusted = [x for x in res["results"] if x.get("price") and x.get("trusted", True)]
        price_note = res.get("note")
        price_source, offers = res["source"], sorted(trusted, key=lambda x: x["price"])[:3] if len(trusted) >= 2 else []
        cleaned = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in (res.get("dropped") or {}).items())
        cleaned = f" (filtered out: {cleaned})" if cleaned else ""
        if len(trusted) >= 2:
            prices = [x["price"] for x in trusted]
            price, best = _price_range(prices), min(trusted, key=lambda x: x["price"])
            note(r, f"{len(prices)} new listings for '{res['item']}' at mainstream stores: {_rs(min(prices))} - {_rs(max(prices))}; "
                    f"typical {_rs(price[0])} - {_rs(price[1])}{cleaned}" + (f". {res['note']}" if res.get("note") else ""))
        else:
            note(r, f"No reliable price for '{res['item']}': {len(trusted)} listing at mainstream stores{cleaned}")

    # --- money ---
    bal, summary, sips = first("get_balance"), first("get_spending_summary"), first("get_sips")
    if bal:
        note(bal, f"Balance {_rs(bal['result']['balance'])} (from your statement, as of {bal['result'].get('as_of', '?')})")
    if summary:
        s = summary["result"]
        week = [sum(v[k] for v in s.get("everyday_by_weekday", {}).values()) for k in range(7)]
        lo, hi, bt = week.index(min(week)), week.index(max(week)), (s.get("forecast") or {}).get("backtest")
        if bt and bt["chosen"] == "weekday":
            how = (f"everyday spending by weekday ({_rs(week[lo])} on {WEEKDAYS[lo]}s to {_rs(week[hi])} on {WEEKDAYS[hi]}s). "
                   f"Back-tested on your last 4 weeks: off by ~{_rs(bt['weekday_miss_per_3_days'])} per 3 days "
                   f"(a flat daily average: ~{_rs(bt['flat_miss_per_3_days'])})")
        else:  # Finance chose the plain average: no weekly pattern that beat it, or too little data to test one
            how = (f"everyday spending at your daily average ({_rs(week[0])}/day)"
                   + (f". Back-tested on your last 4 weeks: off by ~{_rs(bt['flat_miss_per_3_days'])} per 3 days "
                      f"(a weekday pattern did worse: ~{_rs(bt['weekday_miss_per_3_days'])})" if bt else ""))
        note(summary, f"Forecast: salary, rent, bills and SIPs on their usual days; {how}")
    if sips:
        note(sips, f"SIPs {_rs(sips['result']['monthly_total'])}/mo ({len(sips['result']['sips'])} funds)")

    if kind == "other":
        return out("info", "Here's what I found.")  # main.py puts the model's answer here

    if kind == "trip":
        # no fares = no price: a trip priced on hotel + food alone would look far cheaper than it is
        cost, thing = (tuple(map(sum, zip(flights, stay or (0, 0), other or (0, 0)))) if flights else None), intent["city"]
        if intent.get("abroad"):
            deadline_tradeoffs.insert(0, "Going abroad: check your passport and visa first. Many countries need a visa, "
                                         "and it can take days to weeks")
        legs_shown = [{"from": intent["origin"], "to": intent["dest"], "date": str(intent["start"]), **o[0]},
                      {"from": intent["dest"], "to": intent["origin"], "date": str(intent["end"]), **b[0]}] if flights else []
        extra["breakdown"] = [  # one entry per card in the UI; together they add up to the trip cost
            _part("flight", flights, source=flight_source, legs=legs_shown),
            _part("stay", stay, nights=nights, source=hotel["source"] if hotel else "estimate" if stay else None,
                  per_night=list(hotel["per_night"]) if hotel else None, hotel=hotel["example"] if hotel else None),
            _part("other", other, days=nights + 1, source="estimate" if other else None),
        ]
    elif kind == "expense":
        cost, thing = (per_person[0] * intent["people"], per_person[1] * intent["people"]) if per_person else None, intent["item"]
        extra["breakdown"] = [_part("outing", cost, per_person=list(per_person) if per_person else None,
                                    people=intent["people"], source="estimate" if per_person else None)]
    else:
        cost, thing = (intent["price"], intent["price"]) if intent["price"] else price, intent["item"]
        extra["breakdown"] = [_part("product", cost, source="user" if intent["price"] else price_source,
                                    note=None if intent["price"] or not offers else price_note,
                                    offers=[{k: x.get(k) for k in ("title", "store", "price", "mrp", "rating", "reviews", "link")}
                                            for x in ([] if intent["price"] else offers)])]

    if not (bal and summary):
        tradeoffs += deadline_tradeoffs
        if kind in ("purchase", "savings_goal"):
            return out("insufficient_data", f"Plug in Finance and upload your bank statement so I can check {thing} against your money.", cost=cost)
        if free is None:
            return out("insufficient_data", "I can't read your calendar or your money right now. Check the sources below.", cost=cost)
        span = f"{_day(intent['start'])} - {_day(intent['end'])}" if kind == "trip" else f"{_day(intent['start'])} evening"
        if free:
            return out("yes", f"You're free {span}. Looks fine. (Money not checked.)", cost=cost)
        return out("yes_with_conditions", "Only if you clear your calendar. (Money not checked.)", cost=cost)
    if cost is None:
        tradeoffs += deadline_tradeoffs
        if kind == "trip":
            why = f"I don't know the airport for {thing}" if not intent["dest"] else f"I couldn't find flights to {thing} for those dates"
            return out("insufficient_data", f"{why}, so I can't price it yet. Try a bigger city nearby or other dates.")
        return out("insufficient_data", f"I couldn't find a reliable price for {thing} at mainstream stores. Name the exact "
                                        f"model, or tell me the price (e.g. \"for Rs 25,000\").")

    # ---- the cash-flow projection ----
    # whole rupees in, whole rupees out: every line of "the math" on the card adds up exactly
    balance, s, cost = round(bal["result"]["balance"]), summary["result"], tuple(map(round, cost))
    commitments, rates = s["monthly_commitments"], {c: [round(x) for x in v] for c, v in s.get("everyday_by_weekday", {}).items()}
    recurring = [r | {"amount": round(r["amount"])} for r in s.get("recurring", [])]
    try:
        as_of = date.fromisoformat(str(bal["result"].get("as_of"))[:10])
    except ValueError:
        as_of = intent["start"]
    today = intent.get("today") or as_of
    pay_day = max(intent["start"], as_of, today)
    salary_day = _next_salary(pay_day, recurring)
    low_day = salary_day - timedelta(days=1)  # the tightest day: just before the next salary
    cushion = f"{_rs(SAFETY_FLOOR)} safety cushion"
    cut_from = max(as_of, today)  # spending before today already happened: only future days can be skipped

    def cash(day, skip=()):
        if day <= cut_from:
            return balance + _flow(as_of, day, recurring, rates)
        return balance + _flow(as_of, cut_from, recurring, rates) + _flow(cut_from, day, recurring, rates, skip)

    def lowest(amount, skip=(), day=pay_day):
        return cash(_next_salary(day, recurring) - timedelta(days=1), skip) - amount

    fun = [c for c in rates if c in CUTTABLE]
    window_days = (low_day - cut_from).days
    saves = {c: _spend(rates, cut_from, low_day, [c]) for c in fun}  # what skipping each saves by the tightest day
    cash_on_day = cash(pay_day)
    extra |= {"cash_on_day": round(cash_on_day), "pay_day": pay_day.isoformat(), "next_salary": salary_day.isoformat()}

    gap = SAFETY_FLOOR - lowest(cost[1])
    cuts, freed = [], 0
    for c in sorted(fun, key=lambda c: -saves[c]):
        if freed >= gap:
            break
        cuts.append((c, saves[c]))
        freed += saves[c]
    until = f"until payday ({_day(salary_day)})"
    money, skip = [], ()
    if gap <= 0:
        verdict = "yes"
        headline = f"Yes! Even at your tightest point before payday you'd still have {_rs(lowest(cost[1]))}, above your {cushion}."
    elif freed >= gap:
        verdict, skip = "yes_with_conditions", tuple(c for c, _ in cuts)
        headline = f"Doable if you {_plan_phrase(cuts)} {until}. That keeps you above your {cushion}."
        money = [f"{CUTTABLE[c][0].upper()}{CUTTABLE[c][1:]} {until}: saves ~{_rs(v)} (forecast for the {window_days} days left)" for c, v in cuts]
    else:
        skip = tuple(fun)
        # risky = under the cushion but never negative, even at the highest price; any chance of going negative is a no
        verdict = "risky" if cash(pay_day, skip) - cost[1] >= 0 and lowest(cost[1], skip) >= 0 else "no"
        # earliest date it fits: right after one of the next few salaries, cutting back on fun spending until then
        fits, salary = None, salary_day
        for _ in range(6):
            when = salary + timedelta(days=(5 - salary.weekday()) % 7) if kind == "trip" else salary  # trips: next Saturday
            if lowest(cost[1], (), when) >= SAFETY_FLOOR:
                fits = (when, False)
                break
            if lowest(cost[1], skip, when) >= SAFETY_FLOOR:
                fits = (when, True)
                break
            salary = _next_salary(salary, recurring)
        if verdict == "risky":
            headline = f"Possible, but risky: you can pay for it, but before payday you'd dip about {_rs(SAFETY_FLOOR - lowest(cost[1], skip))} below your {cushion}."
        elif fits:
            headline = f"Not just yet, but it fits from {_day(fits[0])}, right after payday."
        else:
            headline = f"Not just yet. {thing[0].upper()}{thing[1:]} needs a few months of saving first."
        if verdict == "no":
            money.append(f"On {_day(pay_day)} you'd have about {_rs(cash_on_day)}, and this costs {_rs(cost[0])} - {_rs(cost[1])}")
        if fits:
            money.append(f"It fits from {_day(fits[0])}" + (", if you cut back on fun spending until then" if fits[1] else " without cutting anything"))
        money.append(f"Cutting back on fun spending {until} saves ~{_rs(sum(saves.values()))} (forecast for the {window_days} days left)")
    if lowest(0) < 0:
        money.insert(0, f"Heads up: at your usual spending you'd run short before payday ({_day(salary_day)}) even without this")
    label = {"Investments (SIP)": "SIP", "Rent (PG, incl. food)": "rent", "Subscriptions": "subscription", "Phone": "phone bill"}
    committed = [f"{label.get(r['category'], r['category'].lower())} {_rs(r['amount'])} ({_day(d)})"
                 for i in range(1, (low_day - cut_from).days + 1) for d in [cut_from + timedelta(days=i)]
                 for r in recurring if r["type"] == "debit" and r["day_of_month"] == d.day]
    if committed:
        more = f" and {len(committed) - 4} more" if len(committed) > 4 else ""
        money.append(f"Still going out before payday: {_join(committed[:4]) if not more else ', '.join(committed[:4])}{more}")
    if best and not intent["price"]:  # priced from the shops (not a price the user gave): where it's cheapest
        mrp = f" (MRP {_rs(best['mrp'])}, {round((1 - best['price'] / best['mrp']) * 100)}% off)" if best.get("mrp") else ""
        stars = f", rated {best['rating']} from {best['reviews']} reviews" if best.get("rating") and best.get("reviews") else ""
        money.append(f"Cheapest new at a mainstream store: {_rs(best['price'])} at {best['store']}{mrp}{stars}")
    if flights and verdict != "no":
        stops = lambda f: f" ({f['stops']} stop{'s' if f['stops'] > 1 else ''})" if f.get("stops") else ""  # noqa: E731
        money.append(f"Book the {o[0]['depart']} {o[0]['airline']}{stops(o[0])} out and {b[0]['depart']} {b[0]['airline']}{stops(b[0])} back, "
                     f"plus a budget stay: keeps it near {_rs(cost[0])}")
    if sips:
        money.append(f"Your SIPs ({_rs(sips['result']['monthly_total'])}/mo) stay untouched")
    tradeoffs[:0] = money
    tradeoffs += deadline_tradeoffs
    if kind == "savings_goal":  # the question is "how much a month?", so lead with that number
        per_month = max(0.0, SAFETY_FLOOR - lowest(cost[1])) * 30 / max(window_days, 1)
        fun_month = sum(sum(rates[c]) for c in fun) * 30 / 7
        if verdict == "yes":
            headline = f"You can afford {thing} by {_day(pay_day)} without changing anything, cushion intact."
        elif verdict == "yes_with_conditions":
            headline = f"Set aside about {_rs(per_month)} a month until {_day(pay_day)} ({_plan_phrase(cuts)}) and {thing} is yours, cushion intact."
        else:
            headline = (f"You'd need to set aside about {_rs(per_month)} a month, more than your fun budget (~{_rs(fun_month)}/mo)."
                        + (f" It fits from {_day(fits[0])}." if fits else ""))
    if free is False and verdict == "yes":
        verdict, headline = "yes_with_conditions", "The money works, but your calendar isn't clear."
    remaining = (lowest(cost[1], skip), lowest(cost[0], skip))
    extra["math"] = _math(balance, as_of, cut_from, low_day, recurring, rates, skip, cost, thing)
    return out(verdict, headline, balance, cost, commitments, remaining)
