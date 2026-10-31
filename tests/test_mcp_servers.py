import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_servers"))
import calendar_server  # noqa: E402
import finance_server  # noqa: E402
import gmail_server  # noqa: E402
import price_server  # noqa: E402
import travel_server  # noqa: E402

LOCKED = {
    "price": {"check_price"},
    "travel": {"search_flights", "search_hotels"},
    "calendar": {"list_events", "find_free_slots"},
    "gmail": {"list_tasks", "get_deadlines"},
    "finance": {"load_statement", "forget_statement", "get_balance", "get_sips", "get_spending_summary", "get_cost_table"},
}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    # Tests never touch Google: force the seeded fallback.
    monkeypatch.setattr(calendar_server, "creds", lambda token=None: None)
    monkeypatch.setattr(gmail_server, "creds", lambda token=None: None)


def test_locked_tool_names_and_write_flags():
    for server in (calendar_server, gmail_server, finance_server, travel_server, price_server):
        tools = asyncio.run(server.mcp.list_tools())
        assert {t.name for t in tools} == LOCKED[server.mcp.name]
        writes = {t.name for t in tools if not t.annotations.readOnlyHint}
        assert writes == ({"load_statement", "forget_statement"} if server.mcp.name == "finance" else set())


def test_finance_reads_the_uploaded_statement(monkeypatch, statement):
    monkeypatch.setattr(finance_server, "STATEMENT", statement)
    assert finance_server.get_balance() == {"balance": 54263, "currency": "INR", "as_of": "2026-10-08", "source": "statement_csv"}
    s = finance_server.get_spending_summary(30)
    # salary, rent, SIPs and bills found by themselves: same amount, a month apart, in all 3 months
    assert [(r["category"], r["day_of_month"], r["amount"]) for r in s["recurring"]] == [
        ("Income", 1, 50000), ("Subscriptions", 3, 119), ("Rent (PG, incl. food)", 5, 10000), ("Investments (SIP)", 10, 3000),
        ("Investments (SIP)", 15, 2000), ("Phone", 15, 299), ("Subscriptions", 20, 199)]
    assert s["monthly_commitments"] == 15617
    # the weekday pattern: club nights on Sundays, parties on Fridays, nothing on weekdays
    assert s["everyday_by_weekday"]["Club"] == [0, 0, 0, 0, 0, 0, 2171]
    assert s["everyday_by_weekday"]["Partying"] == [0, 0, 0, 0, 965, 0, 0]
    # back-test on the last 4 weeks: the weekday forecast misses by far less than the old flat Rs/day
    assert s["forecast"]["backtest"] == {"days": 28, "weekday_miss_per_3_days": 755, "weekday_vs_actual_pct": -12.0,
                                         "flat_miss_per_3_days": 1380, "flat_vs_actual_pct": -22.5, "chosen": "weekday"}
    assert finance_server.get_sips()["sips"] == [
        {"amount": 3000, "day_of_month": 10, "months_seen": 3},
        {"amount": 2000, "day_of_month": 15, "months_seen": 3},
    ]


@pytest.mark.parametrize("name, spend, commitments, chosen", [
    ("manu_statement_spend_30k", 29999, 15617, "weekday"),  # still in the PG (rent), fewer nights out
    ("manu_statement_spend_15k", 15000, 5617, "flat"),  # living at home from here down: no rent
    ("manu_statement_spend_10k", 9999, 2418, "flat"),
    ("manu_statement_spend_8k", 7999, 2418, "flat"),
])
def test_sample_budgets(monkeypatch, tmp_path, name, spend, commitments, chosen):
    # Manu on smaller budgets: the same 3 months (up to 8 Oct), salary and habits, fewer outings. A handful of
    # outings is noise, not a weekly pattern, so for light spenders the weekday model loses the back-test and
    # Finance falls back to the plain daily average per category.
    sys.path.insert(0, str(ROOT / "backend"))
    from statement_import import mask_statement

    receipt = mask_statement(ROOT / "data" / "samples" / f"{name}.csv", tmp_path / "s.csv")
    assert (receipt["rejected"], receipt["to"]) == ([], "2026-10-08")
    monkeypatch.setattr(finance_server, "STATEMENT", tmp_path / "s.csv")
    s = finance_server.get_spending_summary()
    assert (round(s["monthly_avg_spend"]), s["monthly_commitments"]) == (spend, commitments)
    bt = s["forecast"]["backtest"]
    assert bt["chosen"] == chosen and bt[f"{chosen}_miss_per_3_days"] == min(bt["weekday_miss_per_3_days"], bt["flat_miss_per_3_days"])
    week = [sum(v[k] for v in s["everyday_by_weekday"].values()) for k in range(7)]
    assert (len(set(week)) == 1) == (chosen == "flat")  # the plain average is the same every day


def test_no_statement_no_numbers(monkeypatch, tmp_path):
    monkeypatch.setattr(finance_server, "STATEMENT", tmp_path / "none.csv")
    with pytest.raises(ValueError, match="No bank statement uploaded yet"):
        finance_server.get_balance()


def test_load_statement_accepts_only_masked_rows(monkeypatch, tmp_path, statement):
    monkeypatch.setattr(finance_server, "STATEMENT", tmp_path / "session" / "statement.csv")
    raw = "Date,Narration,Debit,Credit,Balance\n2026-10-01,UPI-ananya@okicici,100,,900\n"  # never masked
    bad_row = "date,category,debit,credit,balance\n2026-10-01,Club,100,50,900\n"  # both debit and credit
    for text in (raw, bad_row, "date,category,debit,credit,balance\n"):
        with pytest.raises(ValueError):
            finance_server.load_statement(text)
    assert not (tmp_path / "session" / "statement.csv").exists()  # nothing half-written
    r = finance_server.load_statement(statement.read_text(encoding="utf-8"))
    assert (r["rows"], r["from"], r["as_of"], r["balance"]) == (245, "2026-07-09", "2026-10-08", 54263)


def test_calendar_weekend_free_after_friday_party():
    r = calendar_server.find_free_slots("2026-10-10", "2026-10-11", 60)
    assert r["source"] == "seeded"
    assert r["slots"] == [{"start": "2026-10-10T00:30:00+05:30", "end": "2026-10-12T00:00:00+05:30", "minutes": 2850}]
    titles = [e["title"] for e in calendar_server.list_events("2026-10-09", "2026-10-09")["events"]]
    assert titles == ["Team lunch", "Friday party - Skyline Brewpub"]


def test_gmail_returns_only_deadline_emails_masked():
    r = gmail_server.list_tasks()
    assert [t["deadline"][:10] for t in r["tasks"]] == ["2026-10-09", "2026-10-12", "2026-10-12", "2026-10-20", "2026-11-01",
                                                    "2026-11-02", "2026-11-05", "2026-11-06", "2026-11-12", "2026-11-18"]
    text = json.dumps(r)
    for leak in ("@", "778812345", "4402198765", "Swiggy", "Meghana", "LinkedIn"):  # addresses, account numbers, non-task email
        assert leak not in text
    # The injection arrives as plain data; Guardian (not this server) stops any write the email asks for.
    assert any("Ignore all previous instructions" in t["snippet"] for t in r["tasks"])


def test_travel_layers_live_cached_seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(travel_server, "CACHE", tmp_path / "cache.json")
    calls = []

    async def fake_live(origin, dest, day):
        calls.append(day)
        if len(calls) == 1:
            return [{"airline": "IndiGo", "depart": "06:10", "arrive": "07:25", "price": 4100, "stops": 0}], None
        return None, "SerpAPI 500: boom"

    monkeypatch.setattr(travel_server, "_live", fake_live)
    search = lambda: asyncio.run(travel_server.search_flights("blr", "GOI", "2026-10-10"))  # noqa: E731
    assert search()["source"] == "live"  # live answer, saved to the cache
    assert search()["source"] == "cached" and len(calls) == 1  # fresh cache: no API call
    monkeypatch.setattr(travel_server, "CACHE_MINUTES", 0)
    r = search()  # stale cache + live fails -> the cache, with the reason
    assert (r["source"], r["note"]) == ("cached", "SerpAPI 500: boom")
    (tmp_path / "cache.json").unlink()
    r = search()  # nothing cached + live fails -> seeded
    assert r["source"] == "seeded" and min(f["price"] for f in r["results"]) == 3899
    with pytest.raises(ValueError):
        asyncio.run(travel_server.search_flights("Bangalore", "GOI", "2026-10-10"))


def test_price_check_seeded_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("ORBIT_OFFLINE", "1")
    monkeypatch.setattr(price_server, "CACHE", tmp_path / "prices_cache.json")
    r = asyncio.run(price_server.check_price("iPhone 16 Pro"))  # matches the seeded "iphone" entry
    assert (r["source"], [x["price"] for x in r["results"]]) == ("seeded", [79900, 89900])
    assert asyncio.run(price_server.check_price("unicorn saddle"))["results"] == []
    with pytest.raises(ValueError):
        asyncio.run(price_server.check_price(" "))


def test_serpapi_parsing_keeps_the_cheapest_priced_fares():
    def leg(airline, dep, arr):
        return {"airline": airline, "departure_airport": {"time": f"2026-10-10 {dep}"}, "arrival_airport": {"time": f"2026-10-10 {arr}"}}

    data = {  # shape of a real SerpAPI Google Flights response (unpriced offers come back with price=None)
        "best_flights": [{"price": 8497, "flights": [leg("IndiGo", "13:10", "15:00"), leg("IndiGo", "15:40", "17:05")]},
                         {"price": None, "flights": [leg("Air India Express", "13:05", "14:20")]}],
        "other_flights": [{"price": 6100, "flights": [leg("Akasa Air", "09:00", "10:15")]}],
    }
    assert [(f["airline"], f["price"], f["stops"]) for f in travel_server._fares(data)] == [("Akasa Air", 6100, 0), ("IndiGo", 8497, 1)]


def test_live_errors_never_contain_the_api_key(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "SECRETKEY")
    monkeypatch.delenv("ORBIT_OFFLINE", raising=False)

    async def boom(*args, **kwargs):
        raise httpx.ConnectError("failed: https://serpapi.com/search?api_key=SECRETKEY")

    monkeypatch.setattr(httpx.AsyncClient, "get", boom)
    fares, why = asyncio.run(travel_server._live("BLR", "GOI", "2026-10-10"))
    assert fares is None and "SECRETKEY" not in why


def test_gmail_deadline_formats():
    assert gmail_server._deadline("Q3 report - due 12th October 2026, 10:00").isoformat() == "2026-10-12T10:00:00+05:30"
    assert gmail_server._deadline("Deadline: 12 Oct 2026").isoformat() == "2026-10-12T23:59:00+05:30"
    assert gmail_server._deadline("due 31 Feb 2026") is None
    assert gmail_server._deadline("no date here") is None


def test_gmail_deadlines_in_range():
    r = gmail_server.get_deadlines("2026-10-10", "2026-10-12")
    assert [(t["title"], t["deadline"]) for t in r["tasks"]] == [
        ("Q3 quarterly report - due 12 Oct 2026, 10:00", "2026-10-12T10:00:00+05:30"),
        ("Book your Tuesday badminton court", "2026-10-12T20:00:00+05:30"),
    ]


def test_price_cleaning_keeps_only_the_real_thing():
    # The kinds of listings a live "iphone 16" search really returned (Oct 2026)
    def listing(title, store, price, **kw):
        return {"title": title, "store": store, "price": price, "trusted": store in ("Amazon.in", "Flipkart", "Croma"), **kw}

    listings = [
        listing("iPhone 16 128 GB: 5G Mobile Phone with Camera Control", "Amazon.in", 76999, mrp=89900),
        listing("Apple iPhone 16", "Flipkart", 79900),
        listing("Apple iPhone 16 Plus", "Flipkart", 89900),  # another model
        listing("Apple iPhone 16 Pro Max 256GB", "Croma", 144900),  # another model
        listing("Apple iPhone 16e", "Croma", 59900),  # 16e is not 16
        listing("Refurbished iPhone 16 Plus", "cainid.in", 89000),
        listing("Buy Apple iPhone 16 128GB White Good", "Ovantica.com", 52999, used=True),  # Google's second-hand flag
        listing("1000 Pieces Iphone 16 Pro 128 Gb", "Tradeindia.com", 98950),
        listing("iPhone 16 128 GB: 5G Mobile Phone WhiteWith Apple Care", "Amazon.in", 83374),  # a bundle
        listing("Silicone Case for iPhone 16", "Amazon.in", 499),
        listing("Buy iPhone 16 Smartphone Lowest Price in India", "Bear Hugs", 16999),  # a scam price
        listing("Apple iPhone 16", "Flipkart", 79900),  # duplicate
    ]
    kept, dropped = price_server._clean(listings, "iphone 16")
    assert [(x["store"], x["price"]) for x in kept] == [("Amazon.in", 76999), ("Flipkart", 79900)]
    assert dropped == {"used_or_refurbished": 2, "junk": 2, "accessories": 1, "other_models": 3, "price_outliers": 1, "duplicates": 1}
    ps5, _ = price_server._clean([listing("Sony PlayStation 5 Digital Edition Console", "Amazon.in", 64990),
                                  listing("Marvel's Spider-Man 2 PS5", "Amazon.in", 3999),  # a game, not the console
                                  listing("Sony PS5 Slim Console", "Croma", 54990)], "ps5")
    assert [x["price"] for x in ps5] == [54990, 64990]  # "ps5" also matches "PlayStation 5"
    # A live "hp omen laptop" search: most titles never say "laptop"; the brand and model are enough
    omen, _ = price_server._clean([listing("HP OMEN Transcend 16-u0022TX 13th Gen Intel Core i7 RTX 4050", "Flipkart", 138029),
                                   listing("HP Omen 16-am0076TX Gaming Laptop", "Croma", 189999),
                                   listing("HP OMEN Gaming Mouse", "Amazon.in", 2999),
                                   listing("HP Victus 15 Gaming Laptop", "Amazon.in", 69990)], "hp omen laptop")
    assert [x["price"] for x in omen] == [138029, 189999]
    assert price_server._clean([listing("HP OMEN Transcend 16", "Flipkart", 138029)], "laptop")[0] == []


def test_hotels_are_real_rooms(monkeypatch, tmp_path):
    data = {"properties": [  # the shape of a live Google Hotels answer
        {"type": "hotel", "name": "Zostel Goa (Morjim)", "rate_per_night": {"extracted_lowest": 978}},  # one dorm bed
        {"type": "vacation rental", "name": "Two-Bedroom Apartment", "rate_per_night": {"extracted_lowest": 1189}},
        {"type": "hotel", "name": "Sibaya Beach Resort", "rate_per_night": {"extracted_lowest": 3727}, "overall_rating": 4.1},
        {"type": "hotel", "name": "The Byke Retreat", "rate_per_night": {"extracted_lowest": 1490}, "overall_rating": 4.5},
    ]}
    assert [h["name"] for h in travel_server._hotels(data)] == ["The Byke Retreat", "Sibaya Beach Resort"]
    # with taxes: Google's total for the stay / nights, which is what the hotel's page charges
    taxed = {"properties": [{"type": "hotel", "name": "Vibes Inn", "rate_per_night": {"extracted_lowest": 791},
                             "total_rate": {"extracted_lowest": 2874}}]}
    assert travel_server._hotels(taxed, nights=2)[0]["per_night"] == 1437
    monkeypatch.setenv("ORBIT_OFFLINE", "1")
    monkeypatch.setattr(travel_server, "HOTELS_CACHE", tmp_path / "hotels_cache.json")
    r = asyncio.run(travel_server.search_hotels("Goa", "2026-10-10", "2026-10-11"))
    assert (r["source"], r["nights"], len(r["results"]), r["results"][0]["per_night"]) == ("seeded", 1, 10, 409)
    with pytest.raises(ValueError):
        asyncio.run(travel_server.search_hotels("Goa", "2026-10-11", "2026-10-10"))


def test_price_falls_back_from_a_sku_to_its_model(tmp_path, monkeypatch):
    # A live "hp omen 16-am0076tx" search (Oct 2026): no store lists that SKU, and Amazon's titles drop "HP"
    def listing(title, store, price):
        return {"title": title, "store": store, "price": price, "trusted": store in ("Amazon.in", "Flipkart", "Reliance Digital")}

    listings = [listing("HP OMEN 16-wf0056TX Intel Core i7 13th Gen", "Flipkart", 145299),
                listing("HP OMEN 16 AMD Ryzen AI 7 Gaming Laptop", "Reliance Digital", 166995),
                listing("Omen 16, Intel Core Ultra 7 255H, 8GB RTX 5050, 24GB DDR5", "Amazon.in", 168616),  # no "HP"
                listing("Victus, 13th Gen Intel core i7-13650HX, 6GB RTX 4050", "Amazon.in", 142990),  # not an Omen
                listing("HP OMEN 16L Gaming Desktop PC 35L GT17-0000in", "Flipkart", 409638)]  # a desktop
    assert price_server._family("HP Omen 16-am0076TX") == "hp omen 16"
    assert price_server._family("iPhone 16") is None

    async def live(item):
        return listings, None
    monkeypatch.setattr(price_server, "_live", live)
    monkeypatch.setattr(price_server, "CACHE", tmp_path / "prices_cache.json")
    out = asyncio.run(price_server.check_price("HP Omen 16-am0076TX"))
    assert [x["price"] for x in out["results"]] == [145299, 166995, 168616]
    assert "hp omen 16" in out["note"]


def test_a_hotel_links_to_its_own_google_hotels_page():
    import travel_server

    data = {"properties": [{"type": "hotel", "name": "Vibes Inn", "rate_per_night": {"extracted_lowest": 790},
                            "property_token": "ChkIabc", "link": "http://vibesinn.com/"},
                           {"type": "hotel", "name": "No Token Inn", "rate_per_night": {"extracted_lowest": 900},
                            "link": "https://notoken.example/"}]}
    links = [h["link"] for h in travel_server._hotels(data)]
    assert links == ["https://www.google.com/travel/hotels/entity/ChkIabc?hl=en-IN&gl=in&curr=INR", "https://notoken.example/"]
