"""Question -> intent -> the reads the engine needs. No LLM in this file.

agent.understand() (Gemini) is the primary way to turn a question into an intent; parse() is the
always-works rules fallback. validate() checks every intent in code (dates, airport codes, sizes),
whichever produced it. plan() lists the canonical reads for that intent; only read-only tools are planned.

intent = {"kind": trip|purchase|expense|savings_goal|other, "item", "city", "origin", "dest", "abroad", "start", "end",
          "people", "expense_type", "months", "price"}  (start = the day the money is spent)
"""
import calendar
import re
from datetime import date, timedelta

HOME = "BLR"  # ponytail: Manu's home airport; the optional Location server would supply this
KINDS = ("trip", "purchase", "expense", "savings_goal", "other")
EXPENSE_TYPES = ("fine_dining", "casual_dining", "party", "movie", "concert")  # cost_table keys: <type>_per_person
DOMESTIC = {  # rules fallback only; Gemini knows the nearest airport for any city
    "goa": "GOI", "mumbai": "BOM", "delhi": "DEL", "chennai": "MAA", "hyderabad": "HYD", "kochi": "COK",
    "kerala": "COK", "munnar": "COK", "jaipur": "JAI", "rajasthan": "JAI", "jodhpur": "JDH", "jaisalmer": "JSA",
    "kolkata": "CCU", "pune": "PNQ", "shimla": "IXC", "chandigarh": "IXC", "manali": "KUU", "udaipur": "UDR",
    "varanasi": "VNS", "leh": "IXL", "ladakh": "IXL", "srinagar": "SXR", "kashmir": "SXR", "amritsar": "ATQ",
    "ahmedabad": "AMD", "lucknow": "LKO", "agra": "AGR", "rishikesh": "DED", "dehradun": "DED",
    "darjeeling": "IXB", "sikkim": "IXB", "gangtok": "IXB", "guwahati": "GAU", "shillong": "SHL",
    "andaman": "IXZ", "port blair": "IXZ", "trivandrum": "TRV", "mangalore": "IXE", "coimbatore": "CJB",
    "madurai": "IXM", "vizag": "VTZ", "visakhapatnam": "VTZ", "bhubaneswar": "BBI", "indore": "IDR",
}
ABROAD = {  # "japan" -> the main international airport; Google Flights covers the rest of the country from there
    "japan": "NRT", "tokyo": "NRT", "osaka": "KIX", "kyoto": "KIX", "thailand": "BKK", "bangkok": "BKK",
    "phuket": "HKT", "bali": "DPS", "indonesia": "DPS", "singapore": "SIN", "malaysia": "KUL",
    "kuala lumpur": "KUL", "dubai": "DXB", "uae": "DXB", "abu dhabi": "AUH", "maldives": "MLE",
    "sri lanka": "CMB", "colombo": "CMB", "nepal": "KTM", "kathmandu": "KTM", "bhutan": "PBH",
    "vietnam": "SGN", "hanoi": "HAN", "ho chi minh": "SGN", "hong kong": "HKG", "korea": "ICN", "seoul": "ICN",
    "london": "LHR", "uk": "LHR", "england": "LHR", "paris": "CDG", "france": "CDG", "europe": "CDG",
    "germany": "FRA", "frankfurt": "FRA", "switzerland": "ZRH", "zurich": "ZRH", "italy": "FCO", "rome": "FCO",
    "amsterdam": "AMS", "istanbul": "IST", "doha": "DOH", "qatar": "DOH",
    "usa": "JFK", "america": "JFK", "new york": "JFK", "san francisco": "SFO", "canada": "YYZ", "toronto": "YYZ",
    "australia": "SYD", "sydney": "SYD", "melbourne": "MEL", "mauritius": "MRU",
}
AIRPORTS = DOMESTIC | ABROAD
NOT_PLACES = {"out", "home", "work", "office", "sleep", "bed", "there", "it", "college", "school", "gym", "mall", "market",
              "doctor", "hospital", "park", "beach", "temple", "class", "party", "dinner", "lunch", "movies", "concert"}
MONEY = {"get_balance", "get_spending_summary", "get_sips", "get_cost_table", "list_tasks"}
NEEDS = {  # which tools each kind of question reads (the rules planner's knowledge; Gemini chooses for itself)
    "trip": MONEY | {"list_events", "find_free_slots", "get_deadlines", "search_flights", "search_hotels"},
    "purchase": MONEY | {"check_price"},
    "savings_goal": MONEY | {"check_price"},
    "expense": MONEY | {"list_events"},
}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
NUMBER_WORDS = {w: i for i, w in enumerate(("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"), 1)}


def _upcoming(today, weekday):
    """Next given weekday, today included."""
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def _weekend(today):
    """PLAN P2: "this/next weekend" = the upcoming Saturday-Sunday (never today)."""
    start = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
    return start, start + timedelta(days=1)


def _iso(value, today):
    """A YYYY-MM-DD string within the next ~13 months, else None."""
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
    return d if today <= d <= today + timedelta(days=400) else None


def validate(raw, today):
    """Any intent (Gemini's or parse()'s) -> a complete, sane intent. Code decides what's acceptable, not the model."""
    raw = raw or {}
    kind = raw.get("kind") if raw.get("kind") in KINDS else "other"
    item = " ".join(str(raw.get("item") or "").split())[:60] or None
    intent = {"kind": kind, "item": item, "city": None, "origin": HOME, "dest": None, "abroad": False, "start": None, "end": None,
              "people": 1, "expense_type": None, "months": None, "price": None}
    try:
        price = float(raw.get("price") or 0)
        intent["price"] = price if 0 < price < 1e8 else None
    except (TypeError, ValueError):
        pass
    if kind == "trip":
        city = str(raw.get("city") or "").strip()[:40] or None
        dest = str(raw.get("airport") or raw.get("dest") or "").strip().upper()
        dest = dest if len(dest) == 3 and dest.isalpha() else AIRPORTS.get((city or "").lower())
        abroad = bool(raw.get("abroad")) or (city or "").lower() in ABROAD or dest in ABROAD.values()
        start = _iso(raw.get("start"), today) or _weekend(today)[0]
        end = _iso(raw.get("end"), today)
        # ponytail: nobody flies to Japan for one night, so abroad defaults to 5 days; the receipt states the nights
        end = end if end and start < end <= start + timedelta(days=21) else start + timedelta(days=4 if abroad else 1)
        intent |= {"city": city or "your trip", "dest": dest if dest != HOME else None, "abroad": abroad, "start": start, "end": end}
    elif kind == "expense":
        intent["expense_type"] = raw.get("expense_type") if raw.get("expense_type") in EXPENSE_TYPES else "casual_dining"
        intent["people"] = max(1, min(int(raw.get("people") or 1), 20))
        intent["start"] = _iso(raw.get("start"), today) or today
        intent["item"] = item or intent["expense_type"].replace("_", " ")
    elif kind in ("purchase", "savings_goal"):
        if not item:
            intent["kind"] = "other"
        intent["start"] = _iso(raw.get("start"), today) or today  # paid now, or on the day they said ("next month")
        if kind == "savings_goal":  # ...or on the deadline, for a savings goal
            intent["months"] = max(1, min(int(raw.get("months") or 3), 12))
            intent["start"] = today + timedelta(days=30 * intent["months"])
    if intent["kind"] == "other":
        intent["start"] = None
    intent["today"] = today  # the engine counts cut-backs only from today: past spending can't be skipped
    return intent


def parse(question, today):
    """Rules fallback for when no model answers: good enough for the common phrasings, then validate()."""
    q = question.lower()
    num = lambda pattern: int(m.group(1)) if (m := re.search(pattern, q)) else None  # noqa: E731
    city = next((c for c in AIRPORTS if re.search(rf"\b{c}\b", q)), None)
    place = re.search(r"\b(?:(?:go(?:ing)?|travel(?:l?ing)?|fly(?:ing)?|trip|vacation|holiday|head(?:ing)?)(?:\s+on a trip)?\s+to"
                      r"|visit(?:ing)?)\s+(?:the\s+)?([a-z][a-z ]*?)(?=\s+(?:tomorrow|today|tonight|this|next|on|for|in|with|by|"
                      r"from|over|during|and|after|before|trip|soon)\b|[?.!,]|$)", q)
    place = place.group(1) if place and place.group(1) not in NOT_PLACES else None
    for word, n in NUMBER_WORDS.items():
        q = re.sub(rf"\b{word}\b", str(n), q)
    friends = num(r"with (\d+) (?:other |more )?(?:friends|people|others|of us|colleagues|mates|buddies)")
    raw = {"people": 1 + (friends or 0), "months": num(r"(\d+)\s*months?")}
    if m := re.search(r"(?:₹|rs\.?|inr)\s*([\d,]+)\s*(k)?", q):
        raw["price"] = int(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
    # "buy an HP Omen 16-am0076TX", "get a Sony WH-1000XM5", "is an iPhone 17 within my budget", "price of a PS5"
    item = re.search(r"(?:\b(?:buy|afford|purchase|get|for|order|want|need|spend on|price of|cost of|upgrade to)\s+"
                     r"(?:to (?:buy|get|order|purchase) )?|^(?:is|are) )(?:a |an |the |this |new |my |some )*"
                     r"(?!to\b)([a-z0-9][a-z0-9 +.\-]*?)(?=\s+(?:this|next|within|in|by|for|before|on|at|with|under|from|"
                     r"worth|affordable|right now|now)\b|[?!,]|\.?$)", q)
    raw["item"] = item.group(1).strip(" .-") if item else None
    bought = re.search(r"\b(buy|afford|purchase|get|order|want|need|spend on|price of|cost of|upgrade to|budget)\b", q)
    if not raw["item"] and len(q.split()) <= 5 and not re.search(  # a bare product name: "hp omen laptop"
            r"^(should|can|could|how|what|why|when|where|who|which|is|are|do|does|will|would|i|my)\b", q):
        raw["item"], bought = q.strip(" ?.!") or None, True
    if "save" in q:
        raw["kind"] = "savings_goal"
    elif city:
        raw |= {"kind": "trip", "city": city.title(), "airport": AIRPORTS[city]} | _trip_dates(q, today)
    elif m := re.search(r"\b(dinner|lunch|brunch|party|movie|concert)s?\b", q):
        fancy = re.search(r"\b(fancy|fine|taj|oberoi|leela|itc|five.star|5.star|luxury)\b", q)
        kind = m.group(1)
        raw |= {"kind": "expense", "item": f"{'fancy ' if fancy else ''}{kind}",
                "expense_type": {"party": "party", "movie": "movie", "concert": "concert"}.get(kind, "fine_dining" if fancy else "casual_dining")}
        raw["start"] = str(_when(q, today, weekend=True) or today)
    elif place:  # somewhere the table doesn't know: still a trip, priced only if flights turn up
        raw |= {"kind": "trip", "city": place.title()} | _trip_dates(q, today)
    elif bought and raw["item"]:
        raw["kind"] = "purchase"
        if when := _when(q, today):
            raw["start"] = str(when)
    return validate(raw, today)


MONTH_ABBR = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
MONTHS = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, min(d.day, calendar.monthrange(d.year + y, m + 1)[1]))


def _when(q, today, weekend=False):
    """The day a question is about, or None: "tomorrow", "tonight", "on friday", "15 nov", "november 15th",
    "in 3 days / 2 weeks / 2 months", "next week", "next month", "in december", "this weekend".
    weekend=True (trips, outings): a week or month named without a day means its first Saturday."""
    saturday = (lambda d: d + timedelta(days=(5 - d.weekday()) % 7)) if weekend else (lambda d: d)
    if "tomorrow" in q:
        return today + timedelta(days=1)
    if re.search(r"\b(today|tonight)\b", q):
        return today
    m = re.search(rf"\b(?:(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?)?{MONTHS}\b(?:\s+(\d{{1,2}})(?:st|nd|rd|th)?\b)?", q)
    if m and (m.group(2) != "may" or m.group(1) or m.group(3) or re.search(r"\b(in|by|during) may\b", q)):  # "may I..."
        month, day = MONTH_ABBR.index(m.group(2)[:3]) + 1, m.group(1) or m.group(3)
        try:
            if day:
                d = date(today.year, month, int(day))
                return d if d >= today else date(today.year + 1, month, int(day))
        except ValueError:
            return None  # 31 November
        if month == today.month:
            return saturday(today)
        return saturday(date(today.year + (month < today.month), month, 1))
    if m := re.search(r"\bin (\d+) (day|week|month)s?\b", q):
        n, unit = int(m.group(1)), m.group(2)
        return today + timedelta(days=n) if unit == "day" else saturday(
            today + timedelta(weeks=n) if unit == "week" else _add_months(today, n))
    if re.search(r"\bnext week\b", q):
        return saturday(today + timedelta(days=7 - today.weekday()))  # next Monday, or that week's Saturday
    if re.search(r"\bnext month\b", q):
        return saturday(_add_months(today.replace(day=1), 1))
    if "weekend" in q:
        return _weekend(today)[0]
    if (day := next((i for i, w in enumerate(WEEKDAYS) if w in q), None)) is not None:
        return _upcoming(today, day)
    return None


def _trip_dates(q, today):
    """When the trip starts (_when) and "for 5 days" / "for 3 nights" / "for a week" -> start/end.
    Unsaid -> validate()'s defaults (the upcoming weekend; 5 days abroad)."""
    out, start = {}, _when(q, today, weekend=True)
    if start:
        out["start"] = str(start)
    if m := re.search(r"\bfor (\d+|a) (day|night|week)s?\b", q):
        n = 1 if m.group(1) == "a" else int(m.group(1))
        out["end"] = str((start or _weekend(today)[0]) + timedelta(days=max({"day": n - 1, "night": n, "week": 7 * n}[m.group(2)], 1)))
    return out


def facts(intent, today):
    """Dates, places and argument values, worked out in code, that the LLM planner must use (it never guesses them)."""
    lines = [f"- Today: {today:%a} {today}. Home airport: {intent['origin']}.", f"- Question type: {intent['kind']}."]
    if intent["kind"] == "trip":
        lines += [f"- Trip: {intent['city']} (airport {intent['dest'] or 'none'}), out {intent['start']}, back {intent['end']}.",
                  "- Flight searches are one-way: search each direction."]
    if intent["item"] and intent["kind"] != "trip":
        lines.append(f"- Item: {intent['item']}" + (f" (the user's price: Rs {intent['price']:,.0f})" if intent["price"] else ""))
    ctx = _context(intent, today)
    lines.append("- Use these exact argument values where a tool asks for them: "
                 + ", ".join(f"{k}={v}" for k, v in ctx.items() if v is not None) + ".")
    return "\n".join(lines)


def _context(intent, today):
    """Argument values by parameter name. Tools are filled by what they ask for, never by which server they are on."""
    end = {"trip": intent["end"], "expense": intent["start"]}.get(intent["kind"]) or today + timedelta(days=14)
    if intent["kind"] == "trip":
        end += timedelta(days=1)
    start = intent["start"] if intent["kind"] == "expense" else today
    trip = intent["kind"] == "trip"
    return {"start": start.isoformat(), "end": end.isoformat(), "min_minutes": 60, "days": 30, "item": intent["item"],
            # hotels: the trip's nights, in the city asked about (None outside trips, so the tool isn't planned)
            "city": intent["city"] if trip and intent["dest"] else None,
            "check_in": intent["start"].isoformat() if trip else None,
            "check_out": intent["end"].isoformat() if trip else None}


def plan(intent, tools, today):
    """[(tool_name, args)] the engine needs, from the catalogue registry.discover() returned."""
    ctx, needs, calls = _context(intent, today), NEEDS.get(intent["kind"]), []
    for t in tools:
        if not t["read_only"] or (needs is not None and t["tool"] not in needs):
            continue
        params = set(t["input_schema"].get("properties", {}))
        if {"origin", "dest", "date"} <= params:  # a route search: there and back
            if intent["kind"] == "trip" and intent["dest"]:
                calls.append((t["name"], {"origin": intent["origin"], "dest": intent["dest"], "date": intent["start"].isoformat()}))
                calls.append((t["name"], {"origin": intent["dest"], "dest": intent["origin"], "date": intent["end"].isoformat()}))
        elif params <= {k for k, v in ctx.items() if v is not None}:
            calls.append((t["name"], {p: ctx[p] for p in params}))
    return calls
