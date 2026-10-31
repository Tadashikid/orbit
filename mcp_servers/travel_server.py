"""Travel MCP server on :8104 (streamable HTTP at /mcp): one-way flights and hotel prices.

Layers, always labelled with source + as_of (the same for flights and hotels):
  cached  a live answer from the last few minutes/hours: instant and saves the small SerpAPI quota
  live    SerpAPI Google Flights / Google Hotels (needs SERPAPI_API_KEY in .env); every live answer is saved to the cache
  cached  an older cached answer, if live fails
  seeded  data/flights_seeded.json, data/hotels_seeded.json: the last resort (never labelled live)
Run:  .venv\\Scripts\\python mcp_servers\\travel_server.py
"""
import json
import logging
import os
import re
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
IST = timezone(timedelta(hours=5, minutes=30))
SEEDED = ROOT / "data" / "flights_seeded.json"
# ORBIT_CACHE_DIR: tests and fixture captures use an empty cache, so they never pick up your live searches
CACHES = Path(os.getenv("ORBIT_CACHE_DIR") or ROOT / "data")
CACHE = CACHES / "flights_cache.json"
HOTELS_SEEDED = ROOT / "data" / "hotels_seeded.json"
HOTELS_CACHE = CACHES / "hotels_cache.json"
SERPAPI = "https://serpapi.com/search"
CACHE_MINUTES = 60
HOTEL_CACHE_MINUTES = 6 * 60  # room rates move slower than fares
TIMEOUT_S = 8  # under the registry's 10 s, so a slow search still falls back instead of timing out
MAX_FARES = 5  # ponytail: "high" = 5th-cheapest fare, so one odd premium fare can't inflate the range
MAX_HOTELS = 10
# A hostel's "rate" is one dorm bed, not a room (Goa, Oct 2026: Zostel, goSTOPS, The Hosteller at Rs 300-1,000).
HOSTEL = re.compile(r"hostel|zostel|gostops|hosteller|whoopers|moustache|dorm|backpack|bunk", re.I)

mcp = FastMCP("travel", port=8104 + int(os.getenv("ORBIT_PORT_OFFSET", "0")))  # tests use their own ports
# httpx logs every request URL at INFO, and SerpAPI's key lives in the URL. Never let it reach a log.
logging.getLogger("httpx").setLevel(logging.WARNING)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"routes": {}}


async def _serpapi(params):
    """(data, None) or (None, why). Never puts the exception text in `why`: the request URL contains the key."""
    key = os.getenv("SERPAPI_API_KEY")
    if os.getenv("ORBIT_OFFLINE") or not key:
        return None, "live search off (ORBIT_OFFLINE set or no SERPAPI_API_KEY)"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            r = await client.get(SERPAPI, params=params | {"api_key": key})
        data = r.json()
    except Exception as e:
        return None, f"SerpAPI unreachable ({type(e).__name__})"
    if r.status_code != 200 or "error" in data:
        return None, f"SerpAPI {r.status_code}: {str(data.get('error', ''))[:80]}"
    return data, None


async def _layers(key, cache_path, seeded_path, minutes, fetch):
    """(results, source, as_of, note): fresh cache -> live (then cached) -> older cache -> seeded."""
    now = datetime.now(IST)
    hit = _read(cache_path)["routes"].get(key)
    if hit and now - datetime.fromisoformat(hit["as_of"]) < timedelta(minutes=minutes):
        return hit["results"], "cached", hit["as_of"], None
    results, why = await fetch()
    if results:
        as_of = now.isoformat(timespec="seconds")
        cache = _read(cache_path)  # no await between read and write, so parallel calls can't lose each other's entry
        cache["routes"][key] = {"as_of": as_of, "results": results}
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(cache_path)
        return results, "live", as_of, None
    if hit:
        return hit["results"], "cached", hit["as_of"], why
    seeded = _read(seeded_path)
    results = seeded["routes"].get(key, [])
    return results, "seeded", seeded.get("as_of", ""), why if results else f"{why}; nothing seeded for this search"


def _fares(data):
    """SerpAPI Google Flights JSON -> [{airline, depart, arrive, price, stops}], cheapest first, any number of stops."""
    fares = []
    for offer in data.get("best_flights", []) + data.get("other_flights", []):
        legs = offer.get("flights") or []
        if not legs or not offer.get("price"):
            continue
        fares.append({
            "airline": legs[0].get("airline", "?"),
            "depart": legs[0]["departure_airport"]["time"][-5:],  # "YYYY-MM-DD HH:MM" -> "HH:MM"
            "arrive": legs[-1]["arrival_airport"]["time"][-5:],
            "price": int(offer["price"]),
            "stops": len(legs) - 1,
        })
    # stops count too: abroad the nonstop can cost 3x a one-stop (BLR-NRT tomorrow: Rs 1.59 lakh vs far less via SIN)
    return sorted(fares, key=lambda f: f["price"])[:MAX_FARES]


async def _live(origin, dest, day):
    """(fares, None) or (None, why)."""
    data, why = await _serpapi({"engine": "google_flights", "departure_id": origin, "arrival_id": dest,
                                "outbound_date": day, "type": "2", "currency": "INR", "hl": "en", "gl": "in"})
    if why:
        return None, why
    fares = _fares(data)
    return (fares, None) if fares else (None, "SerpAPI found no flights")


GOOGLE_HOTEL = "https://www.google.com/travel/hotels/entity/{}?hl=en-IN&gl=in&curr=INR"


def _hotels(data, nights=1):
    """SerpAPI Google Hotels JSON -> [{name, per_night, rating, reviews, stars, link}], cheapest first.
    Real rooms only: hostels (a dorm bed's price) and vacation rentals (whole flats) are left out. per_night includes
    taxes and fees (the stay's total / nights) when Google gives it: what you'd pay on the hotel's page."""
    hotels = []
    for p in data.get("properties", []):
        total = (p.get("total_rate") or {}).get("extracted_lowest")
        rate = total / nights if isinstance(total, (int, float)) else (p.get("rate_per_night") or {}).get("extracted_lowest")
        if p.get("type") != "hotel" or not isinstance(rate, (int, float)) or rate <= 0 or HOSTEL.search(p.get("name", "")):
            continue
        hotels.append({"name": p.get("name", "")[:80], "per_night": round(rate), "rating": p.get("overall_rating"),
                       "reviews": p.get("reviews"), "stars": p.get("extracted_hotel_class"),
                       # this exact hotel's Google page (its prices from every site, in rupees), else its own website
                       "link": GOOGLE_HOTEL.format(p["property_token"]) if p.get("property_token") else p.get("link")})
    return sorted(hotels, key=lambda h: h["per_night"])[:MAX_HOTELS]


async def _live_hotels(city, check_in, check_out):
    """(hotels, None) or (None, why). 2-4 star hotels: the range people actually book for a trip like this."""
    data, why = await _serpapi({"engine": "google_hotels", "q": city, "check_in_date": check_in, "check_out_date": check_out,
                                "adults": 1, "currency": "INR", "gl": "in", "hl": "en", "hotel_class": "2,3,4"})
    if why:
        return None, why
    hotels = _hotels(data, (Date.fromisoformat(check_out) - Date.fromisoformat(check_in)).days)
    return (hotels, None) if hotels else (None, "SerpAPI found no hotels")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def search_flights(origin: str, dest: str, date: str) -> dict:
    """One-way flights between two airports (3-letter IATA codes) on an ISO date, cheapest first.
    Every answer says where the prices came from (source: live | cached | seeded) and when (as_of)."""
    origin, dest = origin.strip().upper(), dest.strip().upper()
    if not all(len(c) == 3 and c.isalpha() for c in (origin, dest)):
        raise ValueError("origin and dest must be 3-letter IATA airport codes")
    day = Date.fromisoformat(date).isoformat()
    results, source, as_of, note = await _layers(f"{origin}-{dest}-{day}", CACHE, SEEDED, CACHE_MINUTES,
                                                 lambda: _live(origin, dest, day))
    return {"origin": origin, "dest": dest, "date": day, "results": results, "source": source, "as_of": as_of,
            **({"note": note} if note else {})}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def search_hotels(city: str, check_in: str, check_out: str) -> dict:
    """2-4 star hotels in a city for the nights between two ISO dates: price per night in INR, rating, cheapest first.
    Hostels, dorm beds and vacation rentals are left out. Every answer says where the prices came from
    (source: live | cached | seeded) and when (as_of)."""
    city = " ".join(city.split())[:60]
    if len(city) < 2:
        raise ValueError("city must be a place name")
    start, end = Date.fromisoformat(check_in), Date.fromisoformat(check_out)
    if not start < end <= start + timedelta(days=30):
        raise ValueError("check_out must be 1 to 30 nights after check_in")
    results, source, as_of, note = await _layers(f"{city.lower()}-{start}-{end}", HOTELS_CACHE, HOTELS_SEEDED,
                                                 HOTEL_CACHE_MINUTES, lambda: _live_hotels(city, str(start), str(end)))
    return {"city": city, "check_in": str(start), "check_out": str(end), "nights": (end - start).days,
            "results": results, "source": source, "as_of": as_of, **({"note": note} if note else {})}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
