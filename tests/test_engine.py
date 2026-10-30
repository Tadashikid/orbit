"""Planner + engine against the real server functions (in-process, seeded data). No network."""
import asyncio
import inspect
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "mcp_servers")]
import calendar_server  # noqa: E402
import engine  # noqa: E402
import finance_server  # noqa: E402
import gmail_server  # noqa: E402
import planner  # noqa: E402
import price_server  # noqa: E402
import travel_server  # noqa: E402

Q = "Can I afford a Goa trip next weekend?"
TODAY = date(2026, 10, 8)
KNOWN = ["calendar", "gmail", "travel", "finance", "price"]
CONTRACT = json.loads((ROOT / "contracts" / "verdict.after_finance.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path, statement):
    # Fully seeded, so the numbers are exactly the contract's: no Google, no SerpAPI, no real flight cache.
    monkeypatch.setattr(calendar_server, "creds", lambda: None)
    monkeypatch.setattr(gmail_server, "creds", lambda: None)
    monkeypatch.setenv("ORBIT_OFFLINE", "1")
    monkeypatch.setattr(travel_server, "CACHE", tmp_path / "no_cache.json")
    monkeypatch.setattr(travel_server, "HOTELS_CACHE", tmp_path / "no_hotels_cache.json")
    monkeypatch.setattr(price_server, "CACHE", tmp_path / "no_price_cache.json")
    # Manu's sample statement (conftest.py), masked as an upload would be: balance Rs 54,263 on Thu 08 Oct.
    monkeypatch.setattr(finance_server, "STATEMENT", statement)


def set_balance(monkeypatch, amount):
    """As if the statement ended today at `amount`; the forecast still comes from Manu's statement."""
    monkeypatch.setattr(finance_server, "get_balance",
                        lambda: {"balance": amount, "currency": "INR", "as_of": "2026-10-08", "source": "statement_csv"})


ALL = [calendar_server, gmail_server, travel_server, finance_server, price_server]


def ask(question, servers):
    """What POST /ask does without a model, minus HTTP: rules intent -> plan -> call -> decide."""
    tools, fns = [], {}
    for mod in servers:
        for t in asyncio.run(mod.mcp.list_tools()):
            name = f"{mod.mcp.name}__{t.name}"
            tools.append({"name": name, "tool": t.name, "input_schema": t.inputSchema, "read_only": bool(t.annotations.readOnlyHint)})
            fns[name] = getattr(mod, t.name)
    intent = planner.parse(question, TODAY)
    calls = planner.plan(intent, tools, TODAY)

    def run(fn, args):
        out = fn(**args)
        return asyncio.run(out) if inspect.iscoroutine(out) else out  # search_flights / check_price are async

    results = [{"server": n.split("__")[0], "tool": n.split("__")[1], "args": a, "ok": True, "result": run(fns[n], a), "ms": 0}
               for n, a in calls]
    return engine.decide(question, intent, results, KNOWN), calls


def test_rules_parser_understands_everyday_questions():
    dinner = planner.parse("Can I go to a fancy dinner to taj with 3 friends this saturday", TODAY)
    assert (dinner["kind"], dinner["expense_type"], dinner["people"], dinner["start"]) == ("expense", "fine_dining", 4, date(2026, 10, 10))
    shimla = planner.parse("Can I go on a trip to shimla this week", TODAY)
    assert (shimla["kind"], shimla["dest"]) == ("trip", "IXC")
    laptop = planner.parse("Can i buy a laptop this month", TODAY)
    assert (laptop["kind"], laptop["item"]) == ("purchase", "laptop")
    iphone = planner.parse("how much should i save up to buy an iphone within next 2months", TODAY)
    assert (iphone["kind"], iphone["item"], iphone["months"]) == ("savings_goal", "iphone", 2)
    assert planner.parse("Should I learn guitar?", TODAY)["kind"] == "other"


def test_model_intents_are_validated_in_code():
    bad = planner.validate({"kind": "trip", "city": "Goa", "airport": "not-a-code", "start": "1999-01-01", "end": "2030-01-01"}, TODAY)
    assert (bad["dest"], bad["start"], bad["end"]) == ("GOI", date(2026, 10, 10), date(2026, 10, 11))  # past/absurd dates replaced
    assert planner.validate({"kind": "hack the planet"}, TODAY)["kind"] == "other"
    assert planner.validate({"kind": "expense", "people": 500}, TODAY)["people"] == 20


def test_purchase_out_of_reach_is_gentle_and_has_a_plan():
    v, calls = ask("Can I buy a laptop this month", ALL)
    assert {n.split("__")[0] for n, _ in calls} == {"gmail", "finance", "price"}  # no calendar or flights for a purchase
    assert v["kind"] == "purchase" and v["numbers"]["trip_cost"] == {"low": 81990, "high": 85000}
    # paid today, Thu 08 Oct: the statement's last balance, Rs 54,263
    assert v["verdict"] == "no" and v["numbers"]["cash_on_day"] == 54263
    assert v["headline"] == "Not just yet, but it fits from Tue 01 Dec, right after payday."
    assert "On Thu 08 Oct you'd have about Rs 54,263, and this costs Rs 81,990 - Rs 85,000" in v["tradeoffs"]
    assert "Cheapest new at a mainstream store: Rs 81,990 at Seeded Store B" in v["tradeoffs"]


def test_savings_goal_says_how_much_per_month():
    v, _ = ask("how much should i save up to buy an iphone within next 2months", ALL)
    assert (v["kind"], v["verdict"]) == ("savings_goal", "risky")
    # fun budget = Rs 6,235 a week of forecast fun spending x 30/7
    assert v["headline"] == ("You'd need to set aside about Rs 26,853 a month, more than your fun budget "
                             "(~Rs 26,721/mo). It fits from Fri 01 Jan.")


def test_fancy_dinner_for_four():
    v, _ = ask("Can I go to a fancy dinner to taj with 3 other friends this saturday", ALL)
    assert v["numbers"]["trip_cost"] == {"low": 10000, "high": 24000}  # Rs 2,500-6,000 per person x 4
    assert (v["verdict"], v["headline"]) == ("yes_with_conditions", "Doable if you skip club nights, skip parties and pause "
                                                                    "shopping until payday (Sun 01 Nov). That keeps you above your "
                                                                    "Rs 10,000 safety cushion.")


def test_cutting_back_only_counts_the_days_left(tmp_path, monkeypatch):
    # The bug this replaces: Rs 5,000 today, dinner in 2 days, and the plan counted a month of skipped club nights
    # as if it were cash on Saturday. Saturday's real cash: 5,000 - SIP 3,000 (on the 10th) - the forecast for
    # Friday (Rs 1,305: party night) and Saturday (Rs 1,250: dinner and arcade) = -Rs 555.
    set_balance(monkeypatch, 5000)
    v, _ = ask("Can I go to a fancy dinner to taj this weekend with 3 other friends", ALL)
    assert (v["verdict"], v["numbers"]["cash_on_day"]) == ("no", -555)
    assert v["tradeoffs"][0] == "Heads up: at your usual spending you'd run short before payday (Sun 01 Nov) even without this"
    assert "On Sat 10 Oct you'd have about -Rs 555, and this costs Rs 10,000 - Rs 24,000" in v["tradeoffs"]


def test_planner_dates_directions_and_no_writes():
    trip = planner.parse(Q, TODAY)
    assert (trip["start"], trip["end"], trip["dest"]) == (date(2026, 10, 10), date(2026, 10, 11), "GOI")
    _, calls = ask(Q, [calendar_server, gmail_server, travel_server, finance_server])
    names = [n for n, _ in calls]
    assert "finance__load_statement" not in names  # the rules planner never plans a write
    assert [a for n, a in calls if n == "travel__search_flights"] == [
        {"origin": "BLR", "dest": "GOI", "date": "2026-10-10"},
        {"origin": "GOI", "dest": "BLR", "date": "2026-10-11"},
    ]


def test_before_finance_looks_fine():
    v, _ = ask(Q, [calendar_server, gmail_server, travel_server])
    assert v["verdict"] == "yes" and v["not_read"] == ["finance", "price"]  # a trip doesn't need shop prices
    # Rs 6,120 / Rs 6,880 fares are >1.5x the cheapest, so they're listed but not priced in; plus one hotel night
    # (seeded Google Hotels capture: Rs 1,490 at the budget end to Rs 3,842 typical)
    assert v["numbers"]["trip_cost"] == {"low": 8109 + 1490, "high": 9990 + 3842} and v["numbers"]["balance"] is None
    findings = " | ".join(e["finding"] for e in v["evidence"])
    assert "1 email contains instructions aimed at the AI" in findings
    assert not any("Goa weekend pre-approval" in t for t in v["tradeoffs"])  # injected email never shapes the plan
    assert any("Q3 quarterly report" in t for t in v["tradeoffs"])


def test_after_finance_matches_contract():
    v, _ = ask(Q, [calendar_server, gmail_server, travel_server, finance_server])
    assert v["verdict"] == CONTRACT["verdict"] and v["numbers"] == CONTRACT["numbers"]
    assert v["headline"] == CONTRACT["headline"]
    assert v["not_read"] == ["price"]
    # Manu's club nights are Sundays: 3 Sundays left before payday x Rs 2,171 forecast = Rs 6,513
    assert v["tradeoffs"][0] == "Skip club nights until payday (Sun 01 Nov): saves ~Rs 6,513 (forecast for the 23 days left)"
    assert v["numbers"]["remaining"]["low"] >= v["numbers"]["safety_floor"] == 10000
    assert "Your SIPs (Rs 5,000/mo) stay untouched" in v["tradeoffs"]


def test_other_cities_use_default_cost_estimates():
    v, _ = ask("Can I afford a Chennai trip next weekend?", [calendar_server, gmail_server, travel_server, finance_server])
    finding = next(e["finding"] for e in v["evidence"] if e["tool"] == "get_cost_table")
    assert finding.endswith("(default estimates: no Chennai-specific numbers yet)")


# 25,000: the cheapest version stays above zero but the dearest goes negative, so it is a no, not risky
@pytest.mark.parametrize("balance, verdict", [(200000, "yes"), (30000, "risky"), (25000, "no"), (0, "no")])
def test_balance_extremes(tmp_path, monkeypatch, balance, verdict):
    set_balance(monkeypatch, balance)
    v, _ = ask(Q, [calendar_server, gmail_server, travel_server, finance_server])
    assert v["verdict"] == verdict


def test_not_yet_when_even_the_cheapest_version_goes_below_zero(tmp_path, monkeypatch):
    set_balance(monkeypatch, 0)
    costs = tmp_path / "cost_table.json"
    costs.write_text(json.dumps({"source": "user_estimate", "as_of": "2026-10-08", "items": [
        {"key": "goa_stay_per_night", "low": 50000, "high": 60000},
        {"key": "goa_food_per_day", "low": 800, "high": 1500},
        {"key": "goa_local_transport_per_day", "low": 400, "high": 700}]}))
    monkeypatch.setattr(finance_server, "COST_TABLE", costs)
    v, _ = ask(Q, [calendar_server, gmail_server, travel_server, finance_server])
    assert v["verdict"] == "no" and v["headline"].startswith("Not just yet")


def test_risky_comes_with_a_gentle_plan(tmp_path, monkeypatch):
    # Rs 30,000 today: payable, but before payday you'd sit below the Rs 10,000 cushion even after cutting back.
    set_balance(monkeypatch, 30000)
    v, _ = ask(Q, [calendar_server, gmail_server, travel_server, finance_server])
    assert v["verdict"] == "risky"
    assert v["headline"] == ("Possible, but risky: you can pay for it, but before payday you'd dip about Rs 8,490 "
                             "below your Rs 10,000 safety cushion.")
    assert any(t.startswith("Still going out before payday: SIP Rs 3,000 (Sat 10 Oct)") for t in v["tradeoffs"])
    assert v["numbers"]["remaining"]["low"] < v["numbers"]["safety_floor"]  # shown in red: below the cushion


def test_anything_else_becomes_an_info_answer():
    v, calls = ask("Should I learn guitar?", [calendar_server, finance_server])
    assert (v["kind"], v["verdict"]) == ("other", "info") and calls  # main.py puts the model's answer in the headline


@pytest.mark.parametrize("question", [
    "whats the weather?", "weather tomorrow", "hi", "tell me a joke", "asdfgh",  # small talk and gibberish
    "am I free on saturday", "what did I spend on food",  # questions about the user's own data, not a purchase
])
def test_small_talk_is_never_priced(question):
    assert planner.parse(question, TODAY)["kind"] == "other"


@pytest.mark.parametrize("question, item", [
    ("iPhone 16", "iphone 16"), ("hp omen laptop", "hp omen laptop"), ("sony wh-1000xm5", "sony wh-1000xm5"),
    ("Can I buy a table?", "table"), ("buy a ps5", "ps5"),
])
def test_bare_product_names_still_count(question, item):
    intent = planner.parse(question, TODAY)
    assert (intent["kind"], intent["item"]) == ("purchase", item)


def test_rules_parser_knows_any_destination_and_trip_dates():
    japan = planner.parse("can i go to japan tomorrow", TODAY)
    assert (japan["kind"], japan["dest"], japan["abroad"]) == ("trip", "NRT", True)
    assert (japan["start"], japan["end"]) == (date(2026, 10, 9), date(2026, 10, 13))  # abroad defaults to 5 days
    paris = planner.parse("visit paris on friday for 3 nights", TODAY)
    assert (paris["dest"], paris["start"], paris["end"]) == ("CDG", date(2026, 10, 9), date(2026, 10, 12))
    nowhere = planner.parse("can I fly to Reykjavik next weekend", TODAY)
    assert (nowhere["kind"], nowhere["city"], nowhere["dest"]) == ("trip", "Reykjavik", None)
    assert planner.parse("can i go out this weekend", TODAY)["kind"] == "other"


def test_a_trip_without_fares_is_never_priced_on_hotels_alone():
    v, _ = ask("can i go to japan tomorrow", ALL)  # offline: no seeded BLR-NRT fares
    assert v["verdict"] == "insufficient_data" and v["numbers"]["trip_cost"]["low"] is None
    assert v["headline"].startswith("I couldn't find flights to Japan")


def test_abroad_uses_abroad_costs_and_flags_the_visa(tmp_path, monkeypatch):
    fare = lambda p: [{"airline": "JAL", "depart": "20:00", "arrive": "07:00", "price": p, "stops": 0}]  # noqa: E731
    seeded = tmp_path / "flights.json"
    seeded.write_text(json.dumps({"as_of": "2026-10-08", "routes": {"BLR-NRT-2026-10-09": fare(40000), "NRT-BLR-2026-10-13": fare(38000)}}))
    monkeypatch.setattr(travel_server, "SEEDED", seeded)
    v, _ = ask("can i go to japan tomorrow", ALL)
    # flights 78,000 + 4 nights x 3,500-10,000 + 5 days x (1,500-4,000 food + 500-1,500 transport)
    assert v["numbers"]["trip_cost"] == {"low": 78000 + 14000 + 10000, "high": 78000 + 40000 + 27500}
    assert v["verdict"] == "no" and any("visa" in t for t in v["tradeoffs"])


@pytest.mark.parametrize("question", [Q, "Can I buy a laptop this month", "can i go to a concert today",
                                      "how much should i save up to buy an iphone within next 2months"])
def test_the_math_on_the_card_adds_up_to_the_rupee(question):
    v, _ = ask(question, ALL)
    rows = v["numbers"]["math"]
    assert sum(r["amount"] for r in rows[:-1]) == rows[-1]["amount"] == v["numbers"]["remaining"]["low"]


def test_everyday_forecast_follows_the_weekday_pattern():
    # 9-31 Oct: 4 Fridays x 1,305 + 4 Saturdays x 1,250 + 3 each of Sun-Thu (2,999 + 498 + 343 + 266 + 1,074) = 25,760
    v, _ = ask(Q, [calendar_server, gmail_server, travel_server, finance_server])
    assert {"label": "Everyday spending forecast, 23 days (Fri 09 Oct - Sat 31 Oct)", "amount": -25760} in v["numbers"]["math"]


def test_dates_follow_the_question_not_this_weekend():
    singapore = planner.parse("can i go to singapore next month", TODAY)
    # the first Saturday of November, 5 days abroad
    assert (singapore["dest"], singapore["start"], singapore["end"]) == ("SIN", date(2026, 11, 7), date(2026, 11, 11))
    assert planner.parse("trip to japan on 15 nov for 6 days", TODAY)["start"] == date(2026, 11, 15)
    assert planner.parse("goa in 2 weeks", TODAY)["start"] == date(2026, 10, 24)
    assert planner.parse("can I go to paris in december", TODAY)["start"] == date(2026, 12, 5)
    assert planner.parse("may i go to goa", TODAY)["start"] == date(2026, 10, 10)  # "may I", not the month of May
    assert planner.parse("Can I buy a laptop next month", TODAY)["start"] == date(2026, 11, 1)  # bought after payday
    _, calls = ask("can i go to singapore next month", [travel_server])
    assert [a for n, a in calls if n == "travel__search_flights"] == [
        {"origin": "BLR", "dest": "SIN", "date": "2026-11-07"}, {"origin": "SIN", "dest": "BLR", "date": "2026-11-11"}]


def test_one_listing_is_not_a_market_price(tmp_path, monkeypatch):
    # AirPods Pro 2, Oct 2026: the only "mainstream" hit was a Rs 3,541 case. One listing can't set a price.
    seeded = tmp_path / "prices.json"
    seeded.write_text(json.dumps({"as_of": "2026-10-08", "items": {"airpods": [{"title": "AirPods Pro 2", "store": "amazon.in", "price": 3541}]}}))
    monkeypatch.setattr(price_server, "SEEDED", seeded)
    v, _ = ask("Can I buy airpods pro 2 this month", ALL)
    assert v["verdict"] == "insufficient_data" and "reliable price" in v["headline"]


def test_every_card_has_its_share_and_they_add_up():
    v, _ = ask(Q, [calendar_server, gmail_server, travel_server, finance_server])
    parts, cost = v["numbers"]["breakdown"], v["numbers"]["trip_cost"]
    assert [p["key"] for p in parts] == ["flight", "stay", "other"]
    assert (sum(p["low"] for p in parts), sum(p["high"] for p in parts)) == (cost["low"], cost["high"])
    flight, stay, other = parts
    assert (flight["low"], flight["legs"][0]["from"], flight["legs"][1]["date"]) == (8109, "BLR", "2026-10-11")
    # the stay is real hotel prices (seeded capture), the rest the user's cost table
    assert (stay["per_night"], stay["hotel"]["name"], stay["source"]) == ([1490, 3842], "The Byke Retreat - Royal Pearl", "seeded")
    assert (other["low"], other["high"], other["source"]) == (2400, 4400, "estimate")  # Goa food + scooter, 2 days
    laptop, _ = ask("Can I buy a laptop this month", ALL)
    product = laptop["numbers"]["breakdown"][0]
    assert product["key"] == "product" and [o["price"] for o in product["offers"]] == [81990, 85000]
    dinner, _ = ask("Can I go to a fancy dinner to taj with 3 other friends this saturday", ALL)
    assert dinner["numbers"]["breakdown"] == [{"key": "outing", "low": 10000, "high": 24000, "per_person": [2500, 6000],
                                               "people": 4, "source": "estimate"}]


@pytest.mark.parametrize("question, kind, item", [
    ("Can I get an HP Omen laptop?", "purchase", "hp omen laptop"),
    ("Can I afford the HP Omen 16-am0076TX?", "purchase", "hp omen 16-am0076tx"),  # model numbers keep their dashes
    ("hp omen laptop", "purchase", "hp omen laptop"),  # a bare product name
    ("Is an HP Omen laptop within my budget?", "purchase", "hp omen laptop"),
    ("What is the price of a PS5?", "purchase", "ps5"),
    ("I want to learn guitar", "other", None),  # wanting to do something isn't buying it
])
def test_rules_planner_names_the_exact_item(question, kind, item):
    intent = planner.parse(question, date(2026, 10, 8))
    assert (intent["kind"], intent["item"]) == (kind, item)


def test_rules_read_trips_to_places_without_an_airport():
    trip = planner.parse("Check my budget and calendar for the Gokarna trip.", TODAY)
    assert (trip["kind"], trip["city"]) == ("trip", "Gokarna")
    assert planner.parse("Is there any budget in the calendar?", TODAY)["kind"] == "other"  # never a price search
    assert planner.topics("Is there any budget in the calendar?") == ["calendar", "money"]


@pytest.mark.parametrize("question, item", [("How much is an iPhone 16?", "iphone 16"), ("how much does a ps5 cost", "ps5")])
def test_how_much_questions_are_price_checks(question, item):
    intent = planner.parse(question, TODAY)
    assert (intent["kind"], intent["item"]) == ("purchase", item)
    assert planner.parse("how much did I spend this month", TODAY)["kind"] == "other"  # past spending, not a price
