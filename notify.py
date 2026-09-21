"""
Detects new bina.az listings and sends Telegram alerts.
Runs 3×/day via GitHub Actions cron.

Usage:
  python notify.py              # normal run
  python notify.py --map-only   # regenerate map without scraping
"""
import asyncio
import json
import os
import sys
import urllib.request

from dotenv import load_dotenv

from scraper import (
    SEARCH_URL,
    build_stops,
    extract_cards,
    fetch_item,
    load_search_page,
    nearest_walk,
    open_browser,
    parse_card_text,
    scroll_load_all,
)
from map import make_map

load_dotenv()

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
HEADLESS         = os.environ.get("HEADLESS", "false").lower() == "true"
LISTINGS_FILE = "listings.json"


# ── telegram ──────────────────────────────────────────────────────────────────

def send_telegram(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[no token] {text[:120]}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode()
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:
        print(f"Telegram error: {e}")


def format_message(listing: dict) -> str:
    price  = f"{listing['price']:,} AZN" if listing.get("price") else "?"
    land   = f"{listing['land_area_sot']} sot" if listing.get("land_area_sot") else ""
    detail = " · ".join(filter(None, [listing.get("location"), listing.get("rooms"), listing.get("area_m2"), land]))
    walk   = listing.get("walk_min")
    bus    = ("Bus " + ", ".join(listing["bus_lines"])) if listing.get("bus_lines") else "no named line nearby"
    gmaps  = f"https://www.google.com/maps?q={listing['lat']},{listing['lng']}" if listing.get("lat") else ""

    lines = [
        f"🏠 <b>New listing: {price}</b>",
        f"📍 {detail}",
    ]
    if walk is not None:
        lines.append(f"🚶 {walk} min walk · {bus}")
        if listing.get("stop_name"):
            lines.append(f"   <i>{listing['stop_name']}</i>")
    lines.append(f'🔗 <a href="https://bina.az/items/{listing["id"]}">bina.az</a>')
    if gmaps:
        lines.append(f'📌 <a href="{gmaps}">Google Maps</a>')
    return "\n".join(lines)


# ── enrichment ────────────────────────────────────────────────────────────────

async def enrich(page, card: dict, stops: list) -> dict:
    price, location, rooms, area_m2 = parse_card_text(card["text"])
    item = await fetch_item(page, card["id"])

    if item.get("area_m2_gql"):
        area_m2 = f"{item['area_m2_gql']} m²"

    walk = {}
    if item.get("lat") and item.get("lng"):
        walk = nearest_walk(float(item["lat"]), float(item["lng"]), stops)

    return {
        "id":            card["id"],
        "price":         price,
        "location":      location,
        "rooms":         rooms,
        "area_m2":       area_m2,
        "land_area_sot": item.get("land_area_sot"),
        "lat":           item.get("lat"),
        "lng":           item.get("lng"),
        **walk,
    }


# ── main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    if "--map-only" in sys.argv:
        with open(LISTINGS_FILE) as f:
            make_map(json.load(f))
        return

    listings_by_id = {}
    if os.path.exists(LISTINGS_FILE):
        with open(LISTINGS_FILE) as f:
            listings_by_id = {l["id"]: l for l in json.load(f)}
    seen_ids = set(listings_by_id.keys())

    print(f"Known listings: {len(seen_ids)}")
    stops = build_stops()
    print(f"Stops loaded: {len(stops)}")

    MAX_RETRIES = 3
    cards = []

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"Attempt {attempt}/{MAX_RETRIES}…")
        async with open_browser(headless=HEADLESS) as browser:
            page = await browser.new_page()
            total = await load_search_page(page)
            print(f"Total ads on page: {total}")
            print("Scrolling to load all listings…")
            await scroll_load_all(page)
            cards = await extract_cards(page)
            print(f"Found {len(cards)} listings")

            if len(cards) >= 5:
                current_ids = {c["id"] for c in cards}
                new_cards   = [c for c in cards if c["id"] not in seen_ids]
                print(f"New: {len(new_cards)}")

                if not new_cards:
                    send_telegram(f"🔍 Searched {len(cards)} listings — nothing new.")
                else:
                    for i, card in enumerate(new_cards):
                        print(f"  [{i+1}/{len(new_cards)}] {card['id']}")
                        listing = await enrich(page, card, stops)
                        listings_by_id[listing["id"]] = listing
                        msg = format_message(listing)
                        print(msg)
                        send_telegram(msg)

                seen_ids = current_ids
                break

        if len(cards) < 5:
            if attempt < MAX_RETRIES:
                print(f"Blocked — retrying in 60s…")
                await asyncio.sleep(60)
            else:
                msg = f"⚠️ Scraper blocked after {MAX_RETRIES} attempts — likely Cloudflare."
                print(msg)
                send_telegram(msg)
                return

    listings = list(listings_by_id.values())
    with open(LISTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(listings, f, ensure_ascii=False, indent=2)

    make_map(listings)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
