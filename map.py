"""
Generates houses_map.html from listings.json.
Run directly: python map.py
"""
import json
from scraper import GMAPS_KEY
from score import compute_deal_scores


def _add_unit_prices(listings: list[dict]) -> list[dict]:
    for l in listings:
        price = l.get("price")
        area_str = l.get("area_m2", "")
        try:
            area = float(area_str.replace(" m²", "").replace(",", "."))
        except (ValueError, AttributeError):
            area = None
        l["price_per_m2"] = round(price / area) if area and price else None
        sot = l.get("land_area_sot")
        l["price_per_sot"] = round(price / sot) if sot and price else None
    return listings


def make_map(listings: list[dict]) -> None:
    listings = compute_deal_scores([dict(l) for l in listings])
    listings = _add_unit_prices(listings)
    with_coords = [l for l in listings if l.get("lat") and l.get("lng")]

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
  #filter-bar {{ padding: 8px 12px; border-bottom: 1px solid #eee; flex-shrink: 0; font-size: 12px; color: #666; display: flex; align-items: center; gap: 8px; }}
  #sort-select {{ font-size: 12px; border: 1px solid #ddd; border-radius: 4px; padding: 2px 6px; cursor: pointer; }}
  .score-badge {{
    display: inline-block; font-size: 11px; font-weight: 700;
    padding: 2px 6px; border-radius: 10px; margin-left: 4px;
    color: #fff; vertical-align: middle;
  }}
  .score-good {{ background: #2e7d32; }}
  .score-ok   {{ background: #e65100; }}
  .score-poor {{ background: #b71c1c; }}
</style>
</head>
<body>
<div id="map"></div>
<div id="panel">
  <div id="panel-header">
    Heyet evleri
    <small id="subtitle">loading…</small>
  </div>
  <div id="filter-bar">
    Sort:
    <select id="sort-select">
      <option value="score">Deal score ↓</option>
      <option value="price_asc">Price ↑</option>
      <option value="price_desc">Price ↓</option>
    </select>
  </div>
  <div id="listing-list"></div>
</div>
<script>
const LISTINGS = {json.dumps(with_coords, ensure_ascii=False)};

let map, infoWindow, markers = {{}};

function scoreColor(s) {{
  if (s >= 65) return '#2e7d32';
  if (s >= 40) return '#e65100';
  return '#b71c1c';
}}
function scoreBadgeClass(s) {{
  if (s >= 65) return 'score-good';
  if (s >= 40) return 'score-ok';
  return 'score-poor';
}}

function thumbUrl(l) {{
  return l.photo_url || null;
}}

function buildRow(l, list) {{
  const price     = l.price ? l.price.toLocaleString() + ' AZN' : '?';
  const land      = l.land_area_sot ? l.land_area_sot + ' sot' : '';
  const details   = [l.location, l.rooms, l.area_m2, land].filter(Boolean).join(' · ');
  const busLine   = l.bus_lines?.length ? 'Bus ' + l.bus_lines.join(', ') : 'no named line nearby';
  const walkOk    = l.walk_min != null;
  const walkFar   = l.walk_min > 15;
  const score     = l.deal_score ?? '?';
  const gmaps     = `https://www.google.com/maps?q=${{l.lat}},${{l.lng}}`;
  const unitParts = [
    l.price_per_m2  ? l.price_per_m2.toLocaleString()  + ' AZN/m²'  : null,
    l.price_per_sot ? l.price_per_sot.toLocaleString() + ' AZN/sot' : null,
  ].filter(Boolean).join(' · ');

  const popup = `
    <div style="font-family:sans-serif;min-width:210px;max-width:270px">
      ${{thumbUrl(l) ? `<img src="${{thumbUrl(l)}}" onerror="this.style.display='none'" style="width:100%;height:140px;object-fit:cover;border-radius:4px;margin-bottom:8px;display:block">` : ''}}
      <div style="display:flex;align-items:center;gap:8px">
        <span style="font-size:16px;font-weight:700;color:#6a1b9a">${{price}}</span>
        <span style="background:${{scoreColor(score)}};color:#fff;font-size:12px;font-weight:700;
                     padding:2px 7px;border-radius:10px">Deal ${{score}}/100</span>
      </div>
      <div style="color:#555;font-size:12px;margin-top:3px">${{details}}</div>
      ${{unitParts ? `<div style="color:#888;font-size:11px;margin-top:2px">${{unitParts}}</div>` : ''}}
      ${{walkOk ? `
      <div style="margin-top:7px;padding-top:7px;border-top:1px solid #eee">
        <div style="color:#${{walkFar ? 'e65100' : '388e3c'}};font-size:12px;font-weight:600">
          🚶 ${{l.walk_min}} min walk to nearest stop
        </div>
        <div style="color:#555;font-size:11px;margin-top:2px">${{l.stop_name || ''}}</div>
        <div style="color:#1565c0;font-size:12px;font-weight:600;margin-top:4px">🚌 ${{busLine}}</div>
      </div>` : ''}}
      <div style="display:flex;gap:10px;margin-top:9px;padding-top:7px;border-top:1px solid #eee">
        <a href="https://bina.az/items/${{l.id}}" target="_blank" style="font-size:12px;color:#1a73e8">bina.az →</a>
        <a href="${{gmaps}}" target="_blank" style="font-size:12px;color:#1a73e8">Google Maps →</a>
      </div>
    </div>`;

  const row = document.createElement('div');
  row.className = 'listing-row';
  row.id = 'row-' + l.id;
  row.innerHTML = `
    <div class="price">${{price}}<span class="score-badge ${{scoreBadgeClass(score)}}">${{score}}</span></div>
    <div class="meta">${{details}}</div>
    ${{unitParts ? `<div class="meta" style="color:#aaa">${{unitParts}}</div>` : ''}}
    ${{walkOk ? `<div class="walk ${{walkFar ? 'far' : ''}}">🚶 ${{l.walk_min}} min walk</div>` : ''}}
    <div class="bus">🚌 ${{busLine}}</div>`;
  row.addEventListener('click', () => {{
    map.panTo({{lat: parseFloat(l.lat), lng: parseFloat(l.lng)}});
    map.setZoom(15);
    infoWindow.setContent(popup);
    infoWindow.open(map, markers[l.id]);
    highlight(l.id);
  }});

  list.appendChild(row);
  return {{ popup }};
}}

function renderList(sortKey) {{
  const list = document.getElementById('listing-list');
  list.innerHTML = '';

  const sorted = [...LISTINGS].sort((a, b) => {{
    if (sortKey === 'score')      return (b.deal_score || 0) - (a.deal_score || 0);
    if (sortKey === 'price_asc')  return (a.price || 0) - (b.price || 0);
    if (sortKey === 'price_desc') return (b.price || 0) - (a.price || 0);
    return 0;
  }});

  sorted.forEach(l => buildRow(l, list));
}}

function initMap() {{
  map = new google.maps.Map(document.getElementById('map'), {{
    center: {{lat: 40.54, lng: 50.0}},
    zoom: 12,
  }});
  infoWindow = new google.maps.InfoWindow();
  document.getElementById('subtitle').textContent = LISTINGS.length + ' listings';

  LISTINGS.forEach(l => {{
    const score = l.deal_score ?? 0;
    const marker = new google.maps.Marker({{
      position: {{lat: parseFloat(l.lat), lng: parseFloat(l.lng)}},
      map,
      title: (l.price ? l.price.toLocaleString() + ' AZN' : '?') + ' · Deal ' + score + '/100',
      icon: {{
        path: google.maps.SymbolPath.CIRCLE,
        scale: 8,
        fillColor: scoreColor(score),
        fillOpacity: 0.9,
        strokeColor: '#fff',
        strokeWeight: 2,
      }},
      zIndex: score,
    }});

    const price     = l.price ? l.price.toLocaleString() + ' AZN' : '?';
    const land      = l.land_area_sot ? l.land_area_sot + ' sot' : '';
    const details   = [l.location, l.rooms, l.area_m2, land].filter(Boolean).join(' · ');
    const busLine   = l.bus_lines?.length ? 'Bus ' + l.bus_lines.join(', ') : 'no named line nearby';
    const walkOk    = l.walk_min != null;
    const walkFar   = l.walk_min > 15;
    const gmaps     = `https://www.google.com/maps?q=${{l.lat}},${{l.lng}}`;
    const unitParts = [
      l.price_per_m2  ? l.price_per_m2.toLocaleString()  + ' AZN/m²'  : null,
      l.price_per_sot ? l.price_per_sot.toLocaleString() + ' AZN/sot' : null,
    ].filter(Boolean).join(' · ');

    const popup = `
      <div style="font-family:sans-serif;min-width:210px;max-width:270px">
        <img src="${{thumbUrl(l)}}" onerror="this.style.display='none'"
             style="width:100%;height:140px;object-fit:cover;border-radius:4px;margin-bottom:8px;display:block">
        <div style="display:flex;align-items:center;gap:8px">
          <span style="font-size:16px;font-weight:700;color:#6a1b9a">${{price}}</span>
          <span style="background:${{scoreColor(score)}};color:#fff;font-size:12px;font-weight:700;
                       padding:2px 7px;border-radius:10px">Deal ${{score}}/100</span>
        </div>
        <div style="color:#555;font-size:12px;margin-top:3px">${{details}}</div>
        ${{unitParts ? `<div style="color:#888;font-size:11px;margin-top:2px">${{unitParts}}</div>` : ''}}
        ${{walkOk ? `
        <div style="margin-top:7px;padding-top:7px;border-top:1px solid #eee">
          <div style="color:#${{walkFar ? 'e65100' : '388e3c'}};font-size:12px;font-weight:600">
            🚶 ${{l.walk_min}} min walk to nearest stop
          </div>
          <div style="color:#555;font-size:11px;margin-top:2px">${{l.stop_name || ''}}</div>
          <div style="color:#1565c0;font-size:12px;font-weight:600;margin-top:4px">🚌 ${{busLine}}</div>
        </div>` : ''}}
        <div style="display:flex;gap:10px;margin-top:9px;padding-top:7px;border-top:1px solid #eee">
          <a href="https://bina.az/items/${{l.id}}" target="_blank" style="font-size:12px;color:#1a73e8">bina.az →</a>
          <a href="${{gmaps}}" target="_blank" style="font-size:12px;color:#1a73e8">Google Maps →</a>
        </div>
      </div>`;

    marker.addListener('click', () => {{
      infoWindow.setContent(popup);
      infoWindow.open(map, marker);
      highlight(l.id);
    }});
    markers[l.id] = marker;
  }});

  renderList('score');

  document.getElementById('sort-select').addEventListener('change', e => {{
    renderList(e.target.value);
  }});
}}

function highlight(id) {{
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


if __name__ == "__main__":
    with open("listings.json") as f:
        listings = json.load(f)
    make_map(listings)
