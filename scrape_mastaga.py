import asyncio
import json
import re
import sys
from camoufox.async_api import AsyncCamoufox

SEARCH_URL = (
    "https://bina.az/baki/alqi-satqi/torpaq"
    "?price_to=300000&area_from=3&has_bill_of_sale=true"
    "&location_ids%5B%5D=122&location_ids%5B%5D=119"
    "&location_ids%5B%5D=313&location_ids%5B%5D=117"
)
COORD_HASH = "2b71465916b23b497ba378e6a300c8bb95ed42dfa85f3a6adc6247e3da774444"


def page_url(n):
    return SEARCH_URL + (f"&page={n}" if n > 1 else "")


def parse_card_text(text):
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    # Skip "Agentlik" or similar labels at the start
    while lines and not re.search(r'\d', lines[0]):
        lines.pop(0)
    price = int(re.sub(r'\D', '', lines[0])) if lines else None
    location = lines[1] if len(lines) > 1 else ""
    area = lines[2] if len(lines) > 2 else ""
    return price, location, area


async def extract_page_cards(page):
    # Scroll down to trigger lazy loading
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(1500)
    await page.evaluate("window.scrollTo(0, 0)")

    return await page.evaluate("""() => {
        const seen = new Set();
        const results = [];
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


async def get_total_pages(page):
    return await page.evaluate("""() => {
        const els = [...document.querySelectorAll('[aria-label*="page"], [data-cy*="page"], .pagination a, [class*="paginat"] a')];
        const nums = els.map(e => parseInt(e.innerText)).filter(n => n > 0 && n < 200);
        return nums.length ? Math.max(...nums) : null;
    }""")


async def fetch_coords(page, item_id):
    try:
        data = await page.evaluate("""async ({id, hash}) => {
            const r = await fetch('https://bina.az/graphql', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    operationName: 'UserRelatedItem',
                    variables: {id},
                    extensions: {persistedQuery: {version: 1, sha256Hash: hash}}
                })
            });
            return r.json();
        }""", {"id": item_id, "hash": COORD_HASH})
        item = (data.get("data") or {}).get("item") or {}
        return item.get("latitude"), item.get("longitude")
    except Exception as e:
        return None, None


def update_map(listings):
    with open("routes_map.html", "r", encoding="utf-8") as f:
        html = f.read()

    start_m, end_m = "/* LISTINGS_START */", "/* LISTINGS_END */"
    if start_m in html:
        s, e = html.index(start_m), html.index(end_m) + len(end_m)
        html = html[:s] + html[e:]

    with_coords = [l for l in listings if l.get("lat") and l.get("lng")]
    n = len(with_coords)
    print(f"Injecting {n} markers into routes_map.html")

    inject = f"""/* LISTINGS_START */
const LISTINGS = {json.dumps(with_coords, ensure_ascii=False)};
(function() {{
  const COLOR = '#e65100';
  const markers = [];
  let visible = true;
  function init() {{
    const map = window._gmap;
    if (!map) {{ setTimeout(init, 300); return; }}
    LISTINGS.forEach(l => {{
      const price = l.price ? (l.price.toLocaleString() + ' AZN') : '?';
      const marker = new google.maps.Marker({{
        position: {{lat: parseFloat(l.lat), lng: parseFloat(l.lng)}},
        map,
        title: price,
        icon: {{
          path: google.maps.SymbolPath.CIRCLE,
          scale: 7,
          fillColor: COLOR,
          fillOpacity: 0.9,
          strokeColor: '#fff',
          strokeWeight: 1.5,
        }},
        zIndex: 10,
      }});
      const info = new google.maps.InfoWindow({{
        content: `<div style="font-family:sans-serif;min-width:160px">
          <div style="font-size:15px;font-weight:600;color:#e65100">${{price}}</div>
          <div style="color:#555;font-size:12px">${{l.location || ''}}</div>
          <div style="color:#666;font-size:12px">${{l.area || ''}}</div>
          <a href="https://bina.az/items/${{l.id}}" target="_blank"
             style="font-size:12px;color:#1a73e8;display:block;margin-top:6px">bina.az →</a>
        </div>`
      }});
      marker.addListener('click', () => info.open(map, marker));
      markers.push(marker);
    }});
    const panel = document.getElementById('panel');
    const row = document.createElement('div');
    row.className = 'route-row';
    row.innerHTML = `
      <div class="swatch" style="background:${{COLOR}}"></div>
      <div class="route-label" style="font-size:12px">torpaq</div>
      <div class="route-meta">{n} listings</div>
      <div class="toggle on" id="toggle-listings"></div>`;
    row.addEventListener('click', () => {{
      visible = !visible;
      markers.forEach(m => m.setMap(visible ? map : null));
      document.getElementById('toggle-listings').className = `toggle ${{visible ? 'on' : ''}}`;
    }});
    panel.appendChild(row);
  }}
  init();
}})();
/* LISTINGS_END */"""

    html = html.replace(
        '</script>\n<script src="https://maps.googleapis.com',
        inject + '\n</script>\n<script src="https://maps.googleapis.com'
    )
    with open("routes_map.html", "w", encoding="utf-8") as f:
        f.write(html)


async def scroll_load_all(page):
    """Scroll to bottom repeatedly until no new cards appear."""
    prev_count = 0
    stall_rounds = 0
    round_num = 0
    while stall_rounds < 3:
        round_num += 1
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1800)
        count = await page.evaluate("() => document.querySelectorAll('.item-card').length")
        if count > prev_count:
            print(f"  scroll {round_num}: {count} cards loaded")
            prev_count = count
            stall_rounds = 0
        else:
            stall_rounds += 1
    return prev_count


async def main():
    probe = "--probe" in sys.argv
    all_cards = {}  # id -> card data, deduped

    async with AsyncCamoufox(headless=False) as browser:
        page = await browser.new_page()

        print("Loading search page...")
        await page.goto(SEARCH_URL, wait_until="load", timeout=60000)
        try:
            await page.wait_for_function("() => document.title !== 'Just a moment...'", timeout=30000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        total_count = await page.evaluate("""() => {
            const m = document.body.innerText.match(/\\((\\d+)\\)/);
            return m ? parseInt(m[1]) : null;
        }""")
        print(f"Total ads reported: {total_count}")

        print("Scrolling to load all listings...")
        final_count = await scroll_load_all(page)
        print(f"Finished scrolling: {final_count} cards in DOM")

        raw = await extract_page_cards(page)
        print(f"Extracted {len(raw)} unique cards")

        if probe:
            print(json.dumps(raw[:5], indent=2, ensure_ascii=False))
            return

        for c in raw:
            all_cards[c["id"]] = c

        print(f"\nTotal unique listings: {len(all_cards)}")

        # Parse text and fetch coords
        listings = []
        ids = list(all_cards.keys())
        for i, item_id in enumerate(ids):
            card = all_cards[item_id]
            price, location, area = parse_card_text(card["text"])
            lat, lng = await fetch_coords(page, item_id)
            listings.append({
                "id": item_id,
                "price": price,
                "location": location,
                "area": area,
                "lat": lat,
                "lng": lng,
            })
            if (i + 1) % 20 == 0 or (i + 1) == len(ids):
                with_c = sum(1 for l in listings if l.get("lat"))
                print(f"  coords {i+1}/{len(ids)} ({with_c} have coords)")
            await asyncio.sleep(0.15)

    with open("mastaga_listings.json", "w", encoding="utf-8") as f:
        json.dump(listings, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(listings)} listings to mastaga_listings.json")

    update_map(listings)
    print("Done — open routes_map.html in browser")


asyncio.run(main())
