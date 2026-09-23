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
from datetime import date

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
from score import compute_deal_scores

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


def _coords_close(a: dict, b: dict, threshold: float = 0.002) -> bool:
    try:
        return abs(float(a["lat"]) - float(b["lat"])) < threshold and \
               abs(float(a["lng"]) - float(b["lng"])) < threshold
    except (TypeError, ValueError):
        return False


def find_duplicates(new: dict, existing: list[dict]) -> list[dict]:
    """Return existing listings that look like the same property as `new`."""
    dupes = []
    for e in existing:
        if e["id"] == new["id"]:
            continue
        same_spec = (
            e.get("price")   == new.get("price") and
            e.get("rooms")   == new.get("rooms") and
            e.get("area_m2") == new.get("area_m2") and
            e.get("location") == new.get("location")
        )
        close_coords = new.get("lat") and e.get("lat") and _coords_close(new, e)
        if same_spec or (close_coords and e.get("price") == new.get("price")):
            dupes.append(e)
    return dupes


def _score_label(score: int | None) -> str:
    if score is None:
        return ""
    if score >= 65:
        star = "🟢"
    elif score >= 40:
        star = "🟡"
    else:
        star = "🔴"
    return f"{star} Deal score: <b>{score}/100</b>"


def _unit_prices(listing: dict) -> str:
    parts = []
    price = listing.get("price")
    area_str = listing.get("area_m2", "")
    try:
        area = float(area_str.replace(" m²", "").replace(",", "."))
        if area and price:
            parts.append(f"{round(price / area):,} AZN/m²")
    except (ValueError, AttributeError):
        pass
    sot = listing.get("land_area_sot")
    if sot and price:
        parts.append(f"{round(price / sot):,} AZN/sot")
    return " · ".join(parts)


def format_price_change_message(listing: dict, old_price: int) -> str:
    new_price = listing["price"]
    diff = new_price - old_price
    arrow = "📈" if diff > 0 else "📉"
    sign  = "+" if diff > 0 else ""
    land   = f"{listing['land_area_sot']} sot" if listing.get("land_area_sot") else ""
    detail = " · ".join(filter(None, [listing.get("location"), listing.get("rooms"), listing.get("area_m2"), land]))
    gmaps  = f"https://www.google.com/maps?q={listing['lat']},{listing['lng']}" if listing.get("lat") else ""
    lines = [
        f"{arrow} <b>Price change: {old_price:,} → {new_price:,} AZN ({sign}{diff:,})</b>",
        f"📍 {detail}",
    ]
    unit = _unit_prices(listing)
    if unit:
        lines.append(f"💰 {unit}")
    label = _score_label(listing.get("deal_score"))
    if label:
        lines.append(label)
    lines.append(f'🔗 <a href="https://bina.az/items/{listing["id"]}">bina.az</a>')
    if gmaps:
        lines.append(f'📌 <a href="{gmaps}">Google Maps</a>')
    return "\n".join(lines)


def format_message(listing: dict, duplicates: list[dict] | None = None) -> str:
    price  = f"{listing['price']:,} AZN" if listing.get("price") else "?"
    land   = f"{listing['land_area_sot']} sot" if listing.get("land_area_sot") else ""
    detail = " · ".join(filter(None, [listing.get("location"), listing.get("rooms"), listing.get("area_m2"), land]))
    walk   = listing.get("walk_min")
    bus    = ("Bus " + ", ".join(listing["bus_lines"])) if listing.get("bus_lines") else "no named line nearby"
    gmaps  = f"https://www.google.com/maps?q={listing['lat']},{listing['lng']}" if listing.get("lat") else ""

    header = "⚠️ <b>Possible duplicate: {price}</b>" if duplicates else "🏠 <b>New listing: {price}</b>"
    lines = [
        header.format(price=price),
        f"📍 {detail}",
    ]
    unit = _unit_prices(listing)
    if unit:
        lines.append(f"💰 {unit}")
    if walk is not None:
        lines.append(f"🚶 {walk} min walk · {bus}")
        if listing.get("stop_name"):
            lines.append(f"   <i>{listing['stop_name']}</i>")
    label = _score_label(listing.get("deal_score"))
    if label:
        lines.append(label)
    lines.append(f'🔗 <a href="https://bina.az/items/{listing["id"]}">bina.az</a>')
    if gmaps:
        lines.append(f'📌 <a href="{gmaps}">Google Maps</a>')
    if duplicates:
        lines.append("🔁 Duplicates:")
        for d in duplicates:
            lines.append(f'   • <a href="https://bina.az/items/{d["id"]}">bina.az/items/{d["id"]}</a>')
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
        "photo_url":     card.get("photo_url"),
        "price_history": [{"price": price, "date": date.today().isoformat()}],
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

                # check price changes and backfill photo_url for existing listings
                price_changed = []
                for card in cards:
                    if card["id"] not in seen_ids:
                        continue
                    existing = listings_by_id.get(card["id"])
                    if not existing:
                        continue
                    if card.get("photo_url") and not existing.get("photo_url"):
                        existing["photo_url"] = card["photo_url"]
                    card_price, *_ = parse_card_text(card["text"])
                    if card_price and card_price != existing.get("price"):
                        old_price = existing["price"]
                        existing["price"] = card_price
                        history = existing.get("price_history") or [{"price": old_price, "date": "unknown"}]
                        history.append({"price": card_price, "date": date.today().isoformat()})
                        existing["price_history"] = history
                        price_changed.append((existing, old_price))

                if not new_cards and not price_changed:
                    send_telegram(f"🔍 Searched {len(cards)} listings — nothing new.")
                else:
                    # Enrich all new listings before scoring (scores are relative)
                    new_enriched: list[tuple[dict, list[dict]]] = []
                    for i, card in enumerate(new_cards):
                        print(f"  [{i+1}/{len(new_cards)}] {card['id']}")
                        listing = await enrich(page, card, stops)
                        dupes = find_duplicates(listing, list(listings_by_id.values()))
                        listings_by_id[listing["id"]] = listing
                        new_enriched.append((listing, dupes))

                    # Compute scores across the full updated dataset
                    scored = compute_deal_scores(list(listings_by_id.values()))
                    scores_by_id = {l["id"]: l["deal_score"] for l in scored}
                    for l in listings_by_id.values():
                        l["deal_score"] = scores_by_id.get(l["id"])

                    # Send price-change notifications
                    for listing, old_price in price_changed:
                        msg = format_price_change_message(listing, old_price)
                        print(msg)
                        send_telegram(msg)

                    # Send new-listing notifications
                    for listing, dupes in new_enriched:
                        msg = format_message(listing, duplicates=dupes or None)
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
