"""Price Check MCP server on :8105 (streamable HTTP at /mcp): check_price(item) -> current prices in India.

Layers, always labelled with source + as_of (same idea as the Travel server):
  cached  a live answer from the last CACHE_HOURS: instant, saves the small SerpAPI quota
  live    SerpAPI: Google Shopping India + Amazon.in, in parallel (needs SERPAPI_API_KEY); every live answer is cached
  cached  an older cached answer, if live fails
  seeded  data/prices_seeded.json, the last resort (hand-made demo prices)

Google Shopping mixes the real thing with noise. A search for "iphone 16" came back (live, Oct 2026) with the Plus,
Pro and Pro Max, refurbished and "pre-loved" phones, US carrier-locked imports at Rs 1.3 lakh, a "1000 pieces"
wholesale lot and a Rs 16,999 "Pro Max". So every listing is cleaned before anyone prices with it:
  used      refurbished / renewed / pre-owned / open box (Google's own flag or the title)
  junk      wholesale lots, carrier-locked imports, bundles (AppleCare+), replicas
  accessory cases, covers, chargers... unless the query is for one
  model     another model than the one asked for (asked "iPhone 16": no 16 Plus / 16 Pro / 16e)
  outlier   below half or above twice the median of what's left (scams, odd imports)
Mainstream Indian stores (Amazon, Flipkart, Croma...) are marked trusted; the engine only prices on those.
Run:  .venv\\Scripts\\python mcp_servers\\price_server.py
"""
import asyncio
import json
import logging
import os
import re
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
IST = timezone(timedelta(hours=5, minutes=30))
SEEDED = ROOT / "data" / "prices_seeded.json"
# ORBIT_CACHE_DIR: tests and fixture captures use an empty cache, so they never pick up your live searches
CACHE = Path(os.getenv("ORBIT_CACHE_DIR") or ROOT / "data") / "prices_cache.json"
CACHE_VERSION = 6  # bump when the cleaning rules change, so old cached answers are re-fetched
SERPAPI = "https://serpapi.com/search"
CACHE_HOURS = 6  # shop prices move slower than flights
TIMEOUT_S = 8
MAX_RESULTS = 20
# ponytail: a hand-kept list of mainstream Indian retailers and brand stores; extend as new stores show up
TRUSTED = ("amazon", "flipkart", "croma", "reliance digital", "vijay sales", "tata cliq", "jiomart", "apple", "samsung",
           "oneplus", "xiaomi", "mi.com", "dell", "lenovo", "asus", "acer", "hp online", "hp store", "sony", "lg ", "bose",
           "myntra", "ajio", "nykaa", "decathlon", "ikea", "pepperfry", "urban ladder", "sangeetha", "poorvika",
           "unicorn", "imagine", "iplanet", "aptronix", "boat")
USED = re.compile(r"\b(refurb\w*|renewed|restored|pre-?owned|pre-?loved|second[- ]hand|used|open[- ]box|unboxed)\b", re.I)
JUNK = re.compile(r"\b(locked|verizon|at&t|t-mobile|boost mobile|sprint|pieces|wholesale|bulk|lot of|apple ?care\+?|"
                  r"replica|clone|dummy|first copy|toy)\b", re.I)
ACCESSORY = re.compile(r"\b(case|cover|screen ?guard|protector|tempered|charger|cable|adapter|skin|sleeve|pouch|holder|"
                       r"sticker|back ?panel|stand|compatible|replacement|ear ?pads?|mouse|monitor|headset|backpack)\b", re.I)  # "compatible with" = knock-off
CPU = re.compile(r"\b(core ultra|ryzen ai max\+?|ryzen ai)\b", re.I)  # chips, not models
VARIANTS = {"pro", "max", "plus", "ultra", "mini", "lite", "fe", "air", "se"}  # model words that change the price
STOP = {"a", "an", "the", "new", "buy", "for", "with", "and", "of", "in", "my", "latest"}
ALIASES = {"ps5": "playstation 5", "ps4": "playstation 4", "tv": "television", "fridge": "refrigerator",
           "ac": "air conditioner", "mac": "macbook"}  # a title saying either one matches
# Kind-of-thing words: "HP Omen laptop" -> titles say "HP OMEN 16-ap0068AX Gaming...", often without "laptop".
# Only required when nothing else is named ("laptop" alone still must say laptop).
KINDS = {"laptop", "laptops", "notebook", "phone", "mobile", "smartphone", "headphones", "earphones", "earbuds",
         "tv", "television", "watch", "smartwatch", "tablet", "console", "camera", "speaker", "gaming"}

mcp = FastMCP("price", port=8105 + int(os.getenv("ORBIT_PORT_OFFSET", "0")))  # tests use their own ports
# httpx logs every request URL at INFO, and SerpAPI's key lives in the URL. Never let it reach a log.
logging.getLogger("httpx").setLevel(logging.WARNING)


def _read(path, empty):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty


def _words(text):
    """'Apple iPhone 16 (128 GB)' -> ['apple', 'iphone', '16', '128gb']: lowercase, '128 GB' joined, '16e' kept whole."""
    return re.findall(r"[a-z0-9]+", re.sub(r"(\d)\s+(gb|tb)\b", r"\1\2", text.lower()))


def _family(item):
    """'HP Omen 16-am0076TX' -> 'hp omen 16': the item without its SKU-like codes (letters and digits mixed, 5+ long),
    or None when there is no code to drop."""
    words = _words(item)
    family = [w for w in words if not (len(w) >= 5 and re.search(r"\d", w) and re.search(r"[a-z]", w))]
    return " ".join(family) if family and family != words else None


def _clean(listings, query):
    """Raw shop listings -> (kept, dropped counts). See the module docstring for the rules."""
    asked = [w for w in _words(query) if w not in STOP]
    asked = [w for w in asked if w not in KINDS] or asked  # the brand and model name it; the kind is implied
    specific = any(w.isdigit() for w in asked)  # "iphone 16" names a model; "laptop" doesn't
    dropped = {"used_or_refurbished": 0, "junk": 0, "accessories": 0, "other_models": 0, "price_outliers": 0, "duplicates": 0}
    kept, seen = [], set()
    for x in listings:
        title, words = x["title"], set(_words(x["title"]))
        flat = " ".join(_words(title))
        # Amazon titles drop the brand ("Omen 16, Intel Core Ultra 7..."): there the brand is optional, as long as a
        # model name ("omen") is still required ("iphone 16" keeps "iphone": "16" alone names nothing).
        need = asked[1:] if "amazon" in x["store"].lower() and any(w.isalpha() for w in asked[1:]) else asked
        named = all(w in words or (w in ALIASES and ALIASES[w] in flat) for w in need)
        if x.get("used") or USED.search(title):
            reason = "used_or_refurbished"
        elif JUNK.search(title):
            reason = "junk"
        elif ACCESSORY.search(title) and not ACCESSORY.search(query):
            reason = "accessories"
        elif not named or (specific and (set(_words(CPU.sub("", title))) & VARIANTS) - set(asked)):
            reason = "other_models"
        elif (key := (title.lower()[:60], x["store"].lower(), x["price"])) in seen:
            reason = "duplicates"
        else:
            seen.add(key)
            kept.append(x)
            continue
        dropped[reason] += 1
    if kept:
        # Anchor on the upper half: the thing itself costs more than the games, cases and scams listed beside it.
        prices = sorted(x["price"] for x in kept)
        anchor = statistics.median(prices[len(prices) // 2:])
        ok = [x for x in kept if anchor / 2.5 <= x["price"] <= anchor * 2]
        dropped["price_outliers"] = len(kept) - len(ok)
        kept = ok
    return sorted(kept, key=lambda x: x["price"])[:MAX_RESULTS], {k: v for k, v in dropped.items() if v}


async def _live(item):
    """(listings, None) or (None, why): Google Shopping India (every store) and Amazon.in (the biggest one), in parallel.
    `why` never contains exception text (the URL holds the key)."""
    key = os.getenv("SERPAPI_API_KEY")
    if os.getenv("ORBIT_OFFLINE") or not key:
        return None, "live search off (ORBIT_OFFLINE set or no SERPAPI_API_KEY)"
    searches = (({"engine": "google_shopping", "q": item, "gl": "in", "hl": "en", "location": "India"}, "shopping_results"),
                ({"engine": "amazon", "k": item, "amazon_domain": "amazon.in"}, "organic_results"))
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        answers = await asyncio.gather(*(client.get(SERPAPI, params=p | {"api_key": key}) for p, _ in searches),
                                       return_exceptions=True)
    listings, errors = [], []
    for (params, field), r in zip(searches, answers):
        try:
            data = r.json()  # an exception from gather has no .json(): reported below by type only
            if r.status_code != 200 or "error" in data:
                raise ValueError(str(data.get("error", ""))[:80])
        except Exception as e:
            errors.append(f"{params['engine']}: {type(r if isinstance(r, Exception) else e).__name__}")
            continue
        for s in data.get(field, []):
            price, old = s.get("extracted_price"), s.get("extracted_old_price")
            if not isinstance(price, (int, float)) or price <= 0:
                continue
            store = s.get("source") or ("Amazon.in" if params["engine"] == "amazon" else "?")
            delivery = s.get("delivery")
            listings.append({
                "title": s.get("title", "")[:100], "store": store, "price": round(price),
                "mrp": round(old) if isinstance(old, (int, float)) and old > price else None,
                "rating": s.get("rating"), "reviews": s.get("reviews"),
                "delivery": "; ".join(delivery) if isinstance(delivery, list) else delivery,
                "link": s.get("link_clean") or s.get("link") or s.get("product_link"),  # the store's own page first
                "used": bool(s.get("second_hand_condition")), "trusted": any(t in store.lower() for t in TRUSTED),
            })
    if listings:
        return listings, None
    return None, f"SerpAPI found no prices ({'; '.join(errors)})" if errors else "SerpAPI found no prices"


def _answer(item, results, dropped, source, as_of, note=None):
    return {"item": item, "results": results, "dropped": dropped, "trusted_count": sum(1 for x in results if x.get("trusted")),
            "source": source, "as_of": as_of, **({"note": note} if note else {})}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def check_price(item: str) -> dict:
    """Current prices in India for an item to buy (a short shopping query, e.g. "iPhone 16", "PS5", "laptop").
    Listings are cleaned (no refurbished, accessories, other models, wholesale or scam prices), cheapest first, each
    with store, MRP, rating, reviews, delivery and whether the store is a mainstream (trusted) one.
    Every answer says where the prices came from (source: live | cached | seeded) and when (as_of)."""
    item = " ".join(item.split())[:80]
    if len(item) < 2:
        raise ValueError("item must be a short product name")
    query = item.lower()
    now = datetime.now(IST)

    hit = _read(CACHE, {"items": {}})["items"].get(query)
    hit = hit if hit and hit.get("v") == CACHE_VERSION else None
    if hit and now - datetime.fromisoformat(hit["as_of"]) < timedelta(hours=CACHE_HOURS):
        return _answer(item, hit["results"], hit["dropped"], "cached", hit["as_of"], hit.get("note"))

    listings, why = await _live(item)
    if listings:
        results, dropped = _clean(listings, item)
        family, note = _family(item), None
        if family and sum(1 for x in results if x["trusted"]) < 2:  # shops rarely list the exact SKU: price the model
            loose, loose_dropped = _clean(listings, family)
            if sum(1 for x in loose if x["trusted"]) >= 2:
                results, dropped = loose, loose_dropped
                note = f"No mainstream store lists the {item} itself; these are other {family} configurations"
        as_of = now.isoformat(timespec="seconds")
        cache = _read(CACHE, {"items": {}})  # no await between read and write: parallel calls can't lose entries
        cache["items"][query] = {"v": CACHE_VERSION, "as_of": as_of, "results": results, "dropped": dropped,
                                 **({"note": note} if note else {})}
        tmp = CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(CACHE)
        if results:
            return _answer(item, results, dropped, "live", as_of, note)
        why = f"every listing was filtered out ({', '.join(dropped)}): try naming the exact model"
    if hit:
        return _answer(item, hit["results"], hit["dropped"], "cached", hit["as_of"], why)
    seeded = _read(SEEDED, {"items": {}})
    key = next((k for k in seeded["items"] if k in query), None)  # "iphone 16 128gb" -> "iphone"
    results = [dict(x, trusted=True) for x in seeded["items"].get(key, [])]  # our own labelled estimates
    return _answer(item, results, {}, "seeded", seeded.get("as_of", ""), why if results else f"{why}; no seeded prices for '{item}'")


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
