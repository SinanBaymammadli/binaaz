import asyncio
import json
import math
import re
import sys
from camoufox.async_api import AsyncCamoufox

SEARCH_URL = (
    "https://bina.az/baki/alqi-satqi/heyet-evleri"
    "?room_ids%5B%5D=5%2B&room_ids%5B%5D=4&price_to=300000"
    "&land_area_from=4&has_bill_of_sale=true"
    "&location_ids%5B%5D=122&location_ids%5B%5D=313&location_ids%5B%5D=117"
    "&items_view=list&sorting=bumped_at%2Bdesc"
)
COORD_HASH = "2b71465916b23b497ba378e6a300c8bb95ed42dfa85f3a6adc6247e3da774444"
GMAPS_KEY = "AIzaSyBsgRa2Jy4Fep0LoGsR9XRP6evoyDSyTyE"


# ── geo helpers ───────────────────────────────────────────────────────────────

def haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def build_stop_index():
    with open("ayna_stops.json") as f:
        raw = json.load(f)
    with open("all_buses.json") as f:
        buses = json.load(f)

    # stop_id → list of bus numbers
    stop_buses = {}
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
            slat = float(str(stop.get("latitude", "")).replace(",", "."))
            slng = float(str(stop.get("longitude", "")).replace(",", "."))
            if not (30 < slat < 50 and 40 < slng < 60):
                continue
        except Exception:
            continue
        sid = stop["id"]
        info = stop_buses.get(sid, {})
        stops.append({
            "id": sid,
            "lat": slat,
            "lng": slng,
            "name": info.get("name", f"stop#{sid}"),
            "lines": sorted(info.get("lines", [])),
        })
    return stops


def nearest_stop(lat, lng, stops):
    best_d, best = float("inf"), None
    for s in stops:
        d = haversine(lat, lng, s["lat"], s["lng"])
        if d < best_d:
            best_d, best = d, s
    walk_min = round(best_d / 80, 1)
    return best_d, walk_min, best


# ── scraping ──────────────────────────────────────────────────────────────────

def parse_card_text(text):
    lines = [l.strip().replace("\xa0", " ") for l in text.strip().splitlines() if l.strip()]
    while lines and not re.search(r"\d", lines[0]):
        lines.pop(0)
    price    = int(re.sub(r"\D", "", lines[0])) if lines else None
    location = lines[1] if len(lines) > 1 else ""
    rooms    = ""
    area_m2  = ""
    for l in lines[2:]:
        if "otaqlı" in l and not rooms:
            rooms = l
        elif "m²" in l and not area_m2:
            area_m2 = l
    return price, location, rooms, area_m2


async def scroll_load_all(page):
    """Scroll in viewport-sized steps to trigger IntersectionObserver infinite scroll."""
    await page.set_viewport_size({"width": 1280, "height": 900})
    prev, stalls, rnd = 0, 0, 0
    while stalls < 3:
        rnd += 1
        # Step through page viewport by viewport instead of jumping to bottom
        scroll_height = await page.evaluate("() => document.body.scrollHeight")
        pos = 0
        while pos < scroll_height:
            pos += 800
            await page.evaluate(f"window.scrollTo(0, {pos})")
            await page.wait_for_timeout(200)
        await page.wait_for_timeout(1500)
        count = await page.evaluate("() => document.querySelectorAll('.item-card').length")
        if count > prev:
            print(f"  scroll {rnd}: {count} cards")
            prev, stalls = count, 0
        else:
            stalls += 1
    return prev


async def extract_cards(page):
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(1000)
    return await page.evaluate("""() => {
        const seen = new Set(), results = [];
        document.querySelectorAll('.item-card').forEach(card => {
            const a = card.querySelector('a[href*="/items/"]');
            if (!a) return;
            const m = a.getAttribute('href').match(/\\/items\\/(\\d+)/);
            if (!m) return;
            const id = m[1];
            if (seen.has(id)) return;
            seen.add(id);
            results.push({id, text: card.innerText.trim()});
        });
        return results;
    }""")


async def fetch_coords(page, item_id):
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
                        }
                    }`
                })
            });
            return r.json();
        }""", item_id)
        item = (data.get("data") or {}).get("item") or {}
        land = (item.get("landArea") or {}).get("value")
        area = (item.get("area") or {}).get("value")
        return item.get("latitude"), item.get("longitude"), land, area
    except Exception:
        return None, None, None, None


# ── map generator ─────────────────────────────────────────────────────────────

def make_map(listings):
    with_coords = [l for l in listings if l.get("lat") and l.get("lng")]
    listings_js = json.dumps(with_coords, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Heyet evleri — Maştağa / Albalılıq / Buzovna</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, sans-serif; display: flex; height: 100vh; }}
  #map {{ flex: 1; }}
  #panel {{
    width: 300px; background: #fff; overflow-y: auto;
    border-left: 1px solid #e0e0e0; display: flex; flex-direction: column;
  }}
  #panel-header {{
    background: #6a1b9a; color: #fff; padding: 14px 16px;
    font-weight: 600; font-size: 15px; flex-shrink: 0;
  }}
  #panel-header small {{ display: block; font-weight: 400; font-size: 11px; opacity: .8; margin-top: 2px; }}
  #listing-list {{ flex: 1; overflow-y: auto; }}
  .listing-row {{
    padding: 10px 14px; border-bottom: 1px solid #f0f0f0;
    cursor: pointer; transition: background .15s;
  }}
  .listing-row:hover {{ background: #f9f3ff; }}
  .listing-row.active {{ background: #ede7f6; }}
  .price {{ font-size: 14px; font-weight: 600; color: #6a1b9a; }}
  .meta {{ font-size: 11px; color: #777; margin-top: 2px; }}
  .walk {{ font-size: 11px; color: #388e3c; font-weight: 500; margin-top: 3px; }}
  .walk.far {{ color: #e65100; }}
  .bus {{ font-size: 11px; color: #1565c0; font-weight: 500; margin-top: 2px; }}
  #filter-bar {{
    padding: 8px 12px; border-bottom: 1px solid #eee; flex-shrink: 0;
    font-size: 12px; color: #666;
  }}
</style>
</head>
<body>
<div id="map"></div>
<div id="panel">
  <div id="panel-header">
    Heyet evleri
    <small id="subtitle">loading…</small>
  </div>
  <div id="filter-bar">sorted by price ↓ · click row to pan</div>
  <div id="listing-list"></div>
</div>
<script>
const LISTINGS = {listings_js};

let map, infoWindow, markers = {{}};

function initMap() {{
  map = new google.maps.Map(document.getElementById('map'), {{
    center: {{lat: 40.54, lng: 50.0}},
    zoom: 12,
    mapTypeId: 'roadmap',
  }});
  infoWindow = new google.maps.InfoWindow();

  const list = document.getElementById('listing-list');
  document.getElementById('subtitle').textContent =
    LISTINGS.length + ' listings with coordinates';

  // Sort by price desc
  const sorted = [...LISTINGS].sort((a, b) => (b.price || 0) - (a.price || 0));

  sorted.forEach(l => {{
    const price = l.price ? l.price.toLocaleString() + ' AZN' : '?';
    const walkClass = l.walk_min > 15 ? 'far' : '';
    const busLine = l.bus_lines && l.bus_lines.length ? 'Bus ' + l.bus_lines.join(', ') : 'no named line';

    // Marker
    const marker = new google.maps.Marker({{
      position: {{lat: parseFloat(l.lat), lng: parseFloat(l.lng)}},
      map,
      title: price,
      icon: {{
        path: google.maps.SymbolPath.CIRCLE,
        scale: 8,
        fillColor: '#6a1b9a',
        fillOpacity: 0.9,
        strokeColor: '#fff',
        strokeWeight: 2,
      }},
      zIndex: 5,
    }});

    const gmaps = `https://www.google.com/maps?q=${{l.lat}},${{l.lng}}`;
    const landArea = l.land_area_sot ? l.land_area_sot + ' sot' : '';
    const details = [l.location, l.rooms, l.area_m2, landArea].filter(Boolean).join(' · ');
    const content = `
      <div style="font-family:sans-serif;min-width:210px;max-width:270px">
        <div style="font-size:16px;font-weight:700;color:#6a1b9a">${{price}}</div>
        <div style="color:#555;font-size:12px;margin-top:3px">${{details}}</div>
        <div style="margin-top:7px;padding-top:7px;border-top:1px solid #eee">
          <div style="color:#${{l.walk_min > 15 ? 'e65100' : '388e3c'}};font-size:12px;font-weight:600">
            🚶 ${{l.walk_min}} min walk to nearest stop
          </div>
          <div style="color:#555;font-size:11px;margin-top:2px">${{l.stop_name || ''}}</div>
          <div style="color:#1565c0;font-size:12px;font-weight:600;margin-top:4px">🚌 ${{busLine}}</div>
        </div>
        <div style="display:flex;gap:10px;margin-top:9px;padding-top:7px;border-top:1px solid #eee">
          <a href="https://bina.az/items/${{l.id}}" target="_blank"
             style="font-size:12px;color:#1a73e8;text-decoration:none">bina.az →</a>
          <a href="${{gmaps}}" target="_blank"
             style="font-size:12px;color:#1a73e8;text-decoration:none">Google Maps →</a>
        </div>
      </div>`;

    marker.addListener('click', () => {{
      infoWindow.setContent(content);
      infoWindow.open(map, marker);
      highlightRow(l.id);
    }});
    markers[l.id] = marker;

    // Sidebar row
    const row = document.createElement('div');
    row.className = 'listing-row';
    row.id = 'row-' + l.id;
    row.innerHTML = `
      <div class="price">${{price}}</div>
      <div class="meta">${{details}}</div>
      <div class="walk ${{walkClass}}">🚶 ${{l.walk_min}} min walk</div>
      <div class="bus">🚌 ${{busLine}}</div>`;
    row.addEventListener('click', () => {{
      map.panTo({{lat: parseFloat(l.lat), lng: parseFloat(l.lng)}});
      map.setZoom(15);
      infoWindow.setContent(content);
      infoWindow.open(map, markers[l.id]);
      highlightRow(l.id);
    }});
    list.appendChild(row);
  }});
}}

function highlightRow(id) {{
  document.querySelectorAll('.listing-row').forEach(r => r.classList.remove('active'));
  const r = document.getElementById('row-' + id);
  if (r) {{ r.classList.add('active'); r.scrollIntoView({{block: 'nearest'}}); }}
}}
</script>
<script src="https://maps.googleapis.com/maps/api/js?key={GMAPS_KEY}&callback=initMap" async defer></script>
</body>
</html>"""
    with open("houses_map.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved houses_map.html ({len(with_coords)} markers)")


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    if "--map-only" in sys.argv:
        with open("houses_listings.json") as f:
            listings = json.load(f)
        make_map(listings)
        return

    probe = "--probe" in sys.argv

    print("Building stop index...")
    stops = build_stop_index()
    print(f"  {len(stops)} valid stops loaded")

    async with AsyncCamoufox(headless=False) as browser:
        page = await browser.new_page()
        print("Loading search page...")
        await page.goto(SEARCH_URL, wait_until="load", timeout=60000)
        try:
            await page.wait_for_function("() => document.title !== 'Just a moment...'", timeout=30000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        total = await page.evaluate("""() => {
            const m = document.body.innerText.match(/\\((\\d+)\\)/);
            return m ? parseInt(m[1]) : '?';
        }""")
        print(f"Total ads: {total}")

        print("Scrolling to load all listings...")
        await scroll_load_all(page)

        raw = await extract_cards(page)
        print(f"Extracted {len(raw)} unique cards")

        if probe:
            print(json.dumps(raw[:3], indent=2, ensure_ascii=False))
            return

        listings = []
        print("Fetching coords + nearest stop...")
        for i, card in enumerate(raw):
            price, location, rooms, area_m2 = parse_card_text(card["text"])
            lat, lng, land_area_sot, area_m2_gql = await fetch_coords(page, card["id"])
            # prefer GraphQL area over card text (more accurate)
            if area_m2_gql:
                area_m2 = f"{area_m2_gql} m²"

            walk_m, walk_min, stop = None, None, None
            if lat and lng:
                walk_m, walk_min, stop = nearest_stop(lat, lng, stops)

            listings.append({
                "id": card["id"],
                "price": price,
                "location": location,
                "rooms": rooms,
                "area_m2": area_m2,
                "land_area_sot": land_area_sot,
                "lat": lat,
                "lng": lng,
                "walk_m": round(walk_m) if walk_m else None,
                "walk_min": walk_min,
                "stop_name": stop["name"] if stop else None,
                "bus_lines": stop["lines"] if stop else [],
            })
            if (i + 1) % 10 == 0 or (i + 1) == len(raw):
                print(f"  {i+1}/{len(raw)} done")
            await asyncio.sleep(0.15)

    with open("houses_listings.json", "w", encoding="utf-8") as f:
        json.dump(listings, f, ensure_ascii=False, indent=2)
    print(f"Saved houses_listings.json")

    make_map(listings)
    print("Done — open houses_map.html in browser")


if __name__ == "__main__":
    asyncio.run(main())
