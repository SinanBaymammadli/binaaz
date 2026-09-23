"""
bina.az scraper — browser automation + walk distance calculation.
"""
import asyncio
import json
import math
import re
import time
import urllib.request

from camoufox.async_api import AsyncCamoufox

SEARCH_URL = (
    "https://bina.az/baki/alqi-satqi/heyet-evleri"
    "?room_ids%5B%5D=5%2B&room_ids%5B%5D=4&price_to=250000"
    "&land_area_from=3&has_bill_of_sale=true"
    "&location_ids%5B%5D=122&location_ids%5B%5D=313&location_ids%5B%5D=117"
    "&items_view=list&sorting=bumped_at%2Bdesc"
)

GMAPS_KEY = "AIzaSyBsgRa2Jy4Fep0LoGsR9XRP6evoyDSyTyE"
OSRM_URL = "https://routing.openstreetmap.de/routed-foot/route/v1/foot/{lng1},{lat1};{lng2},{lat2}?overview=false"


# ── browser helpers ───────────────────────────────────────────────────────────

def open_browser(headless: bool = False):
    return AsyncCamoufox(headless=headless)


async def load_search_page(page) -> int:
    # Visit homepage first to establish a session before hitting the search page
    await page.goto("https://bina.az", wait_until="domcontentloaded", timeout=60_000)
    try:
        await page.wait_for_function("() => document.title !== 'Just a moment...'", timeout=30_000)
    except Exception:
        pass
    await page.wait_for_timeout(3_000)

    await page.goto(SEARCH_URL, wait_until="load", timeout=60_000)
    try:
        await page.wait_for_function("() => document.title !== 'Just a moment...'", timeout=30_000)
    except Exception:
        pass
    await page.wait_for_timeout(3_000)

    total = await page.evaluate("""() => {
        const m = document.body.innerText.match(/\\((\\d+)\\)/);
        return m ? parseInt(m[1]) : 0;
    }""")
    return total


async def scroll_load_all(page) -> int:
    """Step through the page viewport-by-viewport to trigger IntersectionObserver."""
    await page.set_viewport_size({"width": 1280, "height": 900})
    prev, stalls = 0, 0
    while stalls < 3:
        scroll_height = await page.evaluate("() => document.body.scrollHeight")
        pos = 0
        while pos < scroll_height:
            pos += 800
            await page.evaluate(f"window.scrollTo(0, {pos})")
            await page.wait_for_timeout(200)
        await page.wait_for_timeout(1_500)
        count = await page.evaluate("() => document.querySelectorAll('.item-card').length")
        if count > prev:
            print(f"  scroll: {count} cards")
            prev, stalls = count, 0
        else:
            stalls += 1
    return prev


async def extract_cards(page) -> list[dict]:
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(1_000)
    return await page.evaluate("""() => {
        const seen = new Set(), results = [];
        document.querySelectorAll('.item-card').forEach(card => {
            const a = card.querySelector('a[href*="/items/"]');
            if (!a) return;
            const m = a.getAttribute('href').match(/\\/items\\/(\\d+)/);
            if (!m) return;
            if (seen.has(m[1])) return;
            seen.add(m[1]);
            const img = card.querySelector('img');
            const photo_url = img ? (img.src || img.dataset.src || null) : null;
            results.push({id: m[1], text: card.innerText.trim(), photo_url});
        });
        return results;
    }""")


def parse_card_text(text: str) -> tuple:
    """Returns (price, location, rooms, area_m2)."""
    lines = [l.strip().replace("\xa0", " ") for l in text.splitlines() if l.strip()]
    while lines and not re.search(r"\d", lines[0]):
        lines.pop(0)
    price = int(re.sub(r"\D", "", lines[0])) if lines else None
    location = lines[1] if len(lines) > 1 else ""
    rooms = area_m2 = ""
    for l in lines[2:]:
        if "otaqlı" in l and not rooms:
            rooms = l
        elif "m²" in l and not area_m2:
            area_m2 = l
    return price, location, rooms, area_m2


async def fetch_item(page, item_id: str) -> dict:
    """Fetch lat, lng, land_area_sot, area_m2 via GraphQL."""
    try:
        data = await page.evaluate("""async (id) => {
            const r = await fetch('https://bina.az/graphql', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    operationName: 'GetItem',
                    variables: {id},
                    query: `query GetItem($id: ID!) {
                        item(id: $id) {
                            id latitude longitude
                            landArea { value }
                            area { value }
                            repaired
                        }
                    }`
                })
            });
            return r.json();
        }""", item_id)
        item = (data.get("data") or {}).get("item") or {}
        repaired = item.get("repaired")
        return {
            "lat": item.get("latitude"),
            "lng": item.get("longitude"),
            "land_area_sot": (item.get("landArea") or {}).get("value"),
            "area_m2_gql": (item.get("area") or {}).get("value"),
            "has_repair": bool(repaired) if repaired is not None else None,
        }
    except Exception:
        return {}


# ── stop index ────────────────────────────────────────────────────────────────

def build_stops() -> list[dict]:
    with open("stops.json") as f:
        raw = json.load(f)
    with open("buses.json") as f:
        buses = json.load(f)

    stop_buses: dict[int, dict] = {}
    for bus_num, bus in buses.items():
        for s in bus.get("stops", []):
            sid = (s.get("stop") or {}).get("id") or s.get("stopId")
            name = (s.get("stop") or {}).get("name", "")
            if sid:
                if sid not in stop_buses:
                    stop_buses[sid] = {"name": name, "lines": set()}
                stop_buses[sid]["lines"].add(bus_num)

    stops = []
    for stop in raw:
        try:
            lat = float(str(stop.get("latitude", "")).replace(",", "."))
            lng = float(str(stop.get("longitude", "")).replace(",", "."))
            if not (30 < lat < 50 and 40 < lng < 60):
                continue
        except Exception:
            continue
        sid = stop["id"]
        info = stop_buses.get(sid, {})
        stops.append({
            "id": sid,
            "lat": lat,
            "lng": lng,
            "name": info.get("name", f"stop#{sid}"),
            "lines": sorted(info.get("lines", [])),
        })
    return stops


# ── walk distance ─────────────────────────────────────────────────────────────

def haversine(lat1, lng1, lat2, lng2) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def osrm_walk(lat1, lng1, lat2, lng2, retries=3) -> tuple[float | None, float | None]:
    url = OSRM_URL.format(lat1=lat1, lng1=lng1, lat2=lat2, lng2=lng2)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.load(r)
            if data.get("code") == "Ok":
                route = data["routes"][0]
                return route["distance"], route["duration"]
            return None, None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                print(f"  OSRM error: {e}")
                return None, None


def nearest_walk(lat: float, lng: float, stops: list[dict], candidates: int = 3) -> dict:
    """Route to nearest N stops, return the one with shortest real walk time."""
    closest = sorted(stops, key=lambda s: haversine(lat, lng, s["lat"], s["lng"]))[:candidates]
    best_dur, best_dist, best_stop = float("inf"), None, None
    for s in closest:
        dist_m, dur_s = osrm_walk(lat, lng, s["lat"], s["lng"])
        time.sleep(0.25)
        if dur_s is not None and dur_s < best_dur:
            best_dur, best_dist, best_stop = dur_s, dist_m, s
    if best_stop:
        return {
            "walk_m": round(best_dist),
            "walk_min": round(best_dur / 60, 1),
            "stop_name": best_stop["name"],
            "bus_lines": best_stop["lines"],
        }
    return {"walk_m": None, "walk_min": None, "stop_name": None, "bus_lines": []}
