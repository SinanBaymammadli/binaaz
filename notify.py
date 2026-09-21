"""
Scrapes bina.az heyet-evleri listings, detects new ones, sends Telegram alerts.
Designed to run 3x/day via GitHub Actions cron.
"""
import asyncio
import json
import math
import os
import sys
import time
import urllib.request
from camoufox.async_api import AsyncCamoufox

# ── imports from project modules ─────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from scrape_houses import (
    SEARCH_URL, COORD_HASH, GMAPS_KEY,
    scroll_load_all, extract_cards, fetch_coords, parse_card_text, make_map,
)
from calc_walk import build_stops, nearest_n, osrm_walk, haversine

# ── config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SEEN_IDS_FILE    = "seen_ids.json"
LISTINGS_FILE    = "houses_listings.json"
HEADLESS         = os.environ.get("HEADLESS", "false").lower() == "true"

# ── telegram ──────────────────────────────────────────────────────────────────
def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[no telegram] {text[:120]}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except Exception as e:
        print(f"Telegram error: {e}")


def format_message(listing):
    price    = f"{listing['price']:,} AZN" if listing.get("price") else "?"
    location = listing.get("location", "")
    rooms    = listing.get("rooms", "")
    area_m2  = listing.get("area_m2", "")
    walk     = listing.get("walk_min")
    stop     = listing.get("stop_name", "")
    bus_lines = listing.get("bus_lines", [])
    bus      = "Bus " + ", ".join(bus_lines) if bus_lines else "no named line nearby"
    gmaps    = f"https://www.google.com/maps?q={listing['lat']},{listing['lng']}" if listing.get("lat") else ""

    details = " · ".join(filter(None, [location, rooms, area_m2]))
    parts = [
        f"🏠 <b>New listing: {price}</b>",
        f"📍 {details}",
    ]
    if walk is not None:
        parts.append(f"🚶 {walk} min walk · {bus}")
        if stop:
            parts.append(f"   <i>{stop}</i>")
    parts.append(f'🔗 <a href="https://bina.az/items/{listing["id"]}">bina.az</a>')
    if gmaps:
        parts.append(f'📌 <a href="{gmaps}">Google Maps</a>')
    return "\n".join(parts)


# ── coord + walk ──────────────────────────────────────────────────────────────
async def enrich_listing(page, card, stops):
    price, location, rooms, area_m2 = parse_card_text(card["text"])
    lat, lng = await fetch_coords(page, card["id"])

    walk_m = walk_min = stop_name = None
    bus_lines = []

    if lat and lng:
        candidates = nearest_n(float(lat), float(lng), stops, n=3)
        best_dur, best_dist, best_stop = float("inf"), None, None
        for s in candidates:
            dist_m, dur_s = osrm_walk(float(lat), float(lng), s["lat"], s["lng"])
            time.sleep(0.25)
            if dur_s is not None and dur_s < best_dur:
                best_dur, best_dist, best_stop = dur_s, dist_m, s
        if best_stop:
            walk_m     = round(best_dist)
            walk_min   = round(best_dur / 60, 1)
            stop_name  = best_stop["name"]
            bus_lines  = best_stop["lines"]

    return {
        "id":        card["id"],
        "price":     price,
        "location":  location,
        "rooms":     rooms,
        "area_m2":   area_m2,
        "lat":       lat,
        "lng":       lng,
        "walk_m":    walk_m,
        "walk_min":  walk_min,
        "stop_name": stop_name,
        "bus_lines": bus_lines,
    }


# ── main ──────────────────────────────────────────────────────────────────────
async def main():
    # Load state
    seen_ids = set(json.loads(open(SEEN_IDS_FILE).read())) if os.path.exists(SEEN_IDS_FILE) else set()
    listings = json.loads(open(LISTINGS_FILE).read()) if os.path.exists(LISTINGS_FILE) else []
    listings_by_id = {l["id"]: l for l in listings}

    print(f"Known listings: {len(seen_ids)}")

    stops = build_stops()
    print(f"Stop index: {len(stops)} stops")

    async with AsyncCamoufox(headless=HEADLESS) as browser:
        page = await browser.new_page()
        print("Loading search page...")
        await page.goto(SEARCH_URL, wait_until="load", timeout=60000)
        try:
            await page.wait_for_function(
                "() => document.title !== 'Just a moment...'", timeout=30000
            )
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        print("Scrolling to load all listings...")
        await scroll_load_all(page)
        cards = await extract_cards(page)
        print(f"Found {len(cards)} listings on page")

        if len(cards) < 5:
            print("Too few listings — likely blocked by Cloudflare. Aborting.")
            return

        current_ids = {c["id"] for c in cards}
        new_cards   = [c for c in cards if c["id"] not in seen_ids]
        print(f"New listings: {len(new_cards)}")

        if not new_cards:
            print("No new listings.")
            seen_ids = current_ids
        else:
            for i, card in enumerate(new_cards):
                print(f"  Enriching {i+1}/{len(new_cards)}: {card['id']}")
                listing = await enrich_listing(page, card, stops)
                listings_by_id[listing["id"]] = listing
                msg = format_message(listing)
                print(msg)
                send_telegram(msg)
                await asyncio.sleep(0.2)

            seen_ids = current_ids  # update to current snapshot

    # Save state
    listings = list(listings_by_id.values())
    with open(LISTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(listings, f, ensure_ascii=False, indent=2)
    with open(SEEN_IDS_FILE, "w") as f:
        json.dump(sorted(seen_ids), f)

    make_map(listings)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
