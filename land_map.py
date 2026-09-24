"""
Generates land_map.html from land_listings.json.
Run directly: python land_map.py
"""
import json
from scraper import GMAPS_KEY
from score import compute_land_scores


def _add_unit_prices(listings: list[dict]) -> list[dict]:
    for l in listings:
        price = l.get("price")
        sot = l.get("land_area_sot")
        l["price_per_sot"] = round(price / sot) if sot and price else None
    return listings


def make_land_map(listings: list[dict]) -> None:
    active = [dict(l) for l in listings if not l.get("deleted_at")]
    active = compute_land_scores(active)
    active = _add_unit_prices(active)
    with_coords = [l for l in active if l.get("lat") and l.get("lng")]

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Torpaq sahələri — Bakı</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, sans-serif; display: flex; height: 100vh; }}
  #map {{ flex: 1; }}
  #panel {{
    width: 300px; background: #fff; overflow-y: auto;
    border-left: 1px solid #e0e0e0; display: flex; flex-direction: column;
  }}
  #panel-header {{
    background: #1b5e20; color: #fff; padding: 14px 16px;
    font-weight: 600; font-size: 15px; flex-shrink: 0;
  }}
  #panel-header small {{ display: block; font-weight: 400; font-size: 11px; opacity: .8; margin-top: 2px; }}
  #listing-list {{ flex: 1; overflow-y: auto; }}
  .listing-row {{
    padding: 10px 14px; border-bottom: 1px solid #f0f0f0;
    cursor: pointer; transition: background .15s;
  }}
  .listing-row:hover {{ background: #f1f8e9; }}
  .listing-row.active {{ background: #dcedc8; }}
  .price {{ font-size: 14px; font-weight: 600; color: #1b5e20; }}
  .meta {{ font-size: 11px; color: #777; margin-top: 2px; }}
  .walk {{ font-size: 11px; color: #388e3c; font-weight: 500; margin-top: 3px; }}
  .walk.far {{ color: #e65100; }}
  .bus {{ font-size: 11px; color: #1565c0; font-weight: 500; margin-top: 2px; }}
  #filter-panel {{ padding: 8px 10px; border-bottom: 1px solid #e0e0e0; flex-shrink: 0; background: #fafafa; }}
  .filter-label {{ font-size: 10px; color: #999; margin-bottom: 3px; margin-top: 6px; }}
  .filter-label:first-child {{ margin-top: 0; }}
  .chip-group {{ display: flex; flex-wrap: wrap; gap: 4px; }}
  .chip {{
    font-size: 11px; padding: 2px 8px; border-radius: 10px;
    border: 1px solid #ddd; background: #fff; cursor: pointer;
    user-select: none; transition: all .12s; white-space: nowrap;
  }}
  .chip:hover {{ border-color: #2e7d32; color: #1b5e20; }}
  .chip.active {{ background: #1b5e20; color: #fff; border-color: #1b5e20; }}
  #f-location {{
    width: 100%; font-size: 11px; border: 1px solid #ddd; border-radius: 4px;
    padding: 3px 4px; background: #fff; cursor: pointer; margin-top: 3px;
  }}
  #filter-sort {{ display: flex; align-items: center; gap: 6px; margin-top: 6px; font-size: 11px; color: #999; }}
  #sort-select {{ font-size: 11px; border: 1px solid #ddd; border-radius: 4px; padding: 2px 5px; flex: 1; }}
  #filter-count {{ font-size: 10px; color: #999; text-align: right; margin-top: 4px; }}
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
    Torpaq sahələri
    <small id="subtitle">loading…</small>
  </div>
  <div id="filter-panel">
    <div class="filter-label">Location</div>
    <select id="f-location" multiple size="3"></select>

    <div class="filter-label">Min score</div>
    <div class="chip-group" id="f-score">
      <span class="chip active" data-val="0">Any</span>
      <span class="chip" data-val="40">40+ 🟡</span>
      <span class="chip" data-val="50">50+</span>
      <span class="chip" data-val="65">65+ 🟢</span>
    </div>

    <div class="filter-label">Max walk to bus</div>
    <div class="chip-group" id="f-walk">
      <span class="chip active" data-val="999">Any</span>
      <span class="chip" data-val="10">≤10 min</span>
      <span class="chip" data-val="15">≤15 min</span>
      <span class="chip" data-val="20">≤20 min</span>
    </div>

    <div id="filter-sort">
      Sort:
      <select id="sort-select">
        <option value="score">Score ↓</option>
        <option value="price_asc">Price ↑</option>
        <option value="price_desc">Price ↓</option>
        <option value="pps_asc">AZN/sot ↑</option>
      </select>
    </div>
    <div id="filter-count"></div>
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

function activeChips(groupId) {{
  return [...document.querySelectorAll(`#${{groupId}} .chip.active`)].map(c => c.dataset.val);
}}

function matchesFilters(l) {{
  const locSel = document.getElementById('f-location');
  const selLocs = [...locSel.selectedOptions].map(o => o.value);
  if (selLocs.length && !selLocs.includes(l.location)) return false;
  const minScore = parseInt(activeChips('f-score')[0] ?? '0');
  if ((l.deal_score ?? 0) < minScore) return false;
  const maxWalk = parseFloat(activeChips('f-walk')[0] ?? '999');
  if (l.walk_min != null && l.walk_min > maxWalk) return false;
  return true;
}}

function applyFilters() {{
  const filtered = LISTINGS.filter(matchesFilters);
  Object.values(markers).forEach(m => m.setVisible(false));
  filtered.forEach(l => {{ if (markers[l.id]) markers[l.id].setVisible(true); }});
  renderList(document.getElementById('sort-select').value, filtered);
  const total = LISTINGS.length;
  document.getElementById('filter-count').textContent =
    filtered.length === total ? '' : `${{filtered.length}} of ${{total}} shown`;
  document.getElementById('subtitle').textContent =
    filtered.length === total ? `${{total}} listings` : `${{filtered.length}} / ${{total}}`;
}}

function buildRow(l, list) {{
  const price    = l.price ? l.price.toLocaleString() + ' AZN' : '?';
  const area     = l.land_area_sot ? l.land_area_sot + ' sot' : '';
  const details  = [l.location, area].filter(Boolean).join(' · ');
  const pps      = l.price_per_sot ? l.price_per_sot.toLocaleString() + ' AZN/sot' : '';
  const busLine  = l.bus_lines?.length ? 'Bus ' + l.bus_lines.join(', ') : 'no named line nearby';
  const walkOk   = l.walk_min != null;
  const walkFar  = l.walk_min > 15;
  const score    = l.deal_score ?? '?';
  const gmaps    = `https://www.google.com/maps?q=${{l.lat}},${{l.lng}}`;
  const thumb    = l.photo_url || null;

  const popup = `
    <div style="font-family:sans-serif;min-width:210px;max-width:270px">
      ${{thumb ? `<img src="${{thumb}}" onerror="this.style.display='none'" style="width:100%;height:140px;object-fit:cover;border-radius:4px;margin-bottom:8px;display:block">` : ''}}
      <div style="display:flex;align-items:center;gap:8px">
        <span style="font-size:16px;font-weight:700;color:#1b5e20">${{price}}</span>
        <span style="background:${{scoreColor(score)}};color:#fff;font-size:12px;font-weight:700;padding:2px 7px;border-radius:10px">Deal ${{score}}/100</span>
      </div>
      <div style="color:#555;font-size:12px;margin-top:3px">${{details}}</div>
      ${{pps ? `<div style="color:#888;font-size:11px;margin-top:2px">${{pps}}</div>` : ''}}
      ${{walkOk ? `
      <div style="margin-top:7px;padding-top:7px;border-top:1px solid #eee">
        <div style="color:#${{walkFar ? 'e65100' : '388e3c'}};font-size:12px;font-weight:600">🚶 ${{l.walk_min}} min walk to nearest stop</div>
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
    ${{pps ? `<div class="meta" style="color:#aaa">${{pps}}</div>` : ''}}
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
}}

function renderList(sortKey, subset) {{
  const list = document.getElementById('listing-list');
  list.innerHTML = '';
  const items = subset ?? LISTINGS;
  const sorted = [...items].sort((a, b) => {{
    if (sortKey === 'score')     return (b.deal_score || 0) - (a.deal_score || 0);
    if (sortKey === 'price_asc') return (a.price || 0) - (b.price || 0);
    if (sortKey === 'price_desc')return (b.price || 0) - (a.price || 0);
    if (sortKey === 'pps_asc')   return (a.price_per_sot || 0) - (b.price_per_sot || 0);
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
      title: (l.price ? l.price.toLocaleString() + ' AZN' : '?') + ' · ' + (l.land_area_sot || '?') + ' sot · Deal ' + score + '/100',
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

    const price   = l.price ? l.price.toLocaleString() + ' AZN' : '?';
    const area    = l.land_area_sot ? l.land_area_sot + ' sot' : '';
    const details = [l.location, area].filter(Boolean).join(' · ');
    const pps     = l.price_per_sot ? l.price_per_sot.toLocaleString() + ' AZN/sot' : '';
    const busLine = l.bus_lines?.length ? 'Bus ' + l.bus_lines.join(', ') : 'no named line nearby';
    const walkOk  = l.walk_min != null;
    const walkFar = l.walk_min > 15;
    const gmaps   = `https://www.google.com/maps?q=${{l.lat}},${{l.lng}}`;
    const thumb   = l.photo_url || null;

    const popup = `
      <div style="font-family:sans-serif;min-width:210px;max-width:270px">
        ${{thumb ? `<img src="${{thumb}}" onerror="this.style.display='none'" style="width:100%;height:140px;object-fit:cover;border-radius:4px;margin-bottom:8px;display:block">` : ''}}
        <div style="display:flex;align-items:center;gap:8px">
          <span style="font-size:16px;font-weight:700;color:#1b5e20">${{price}}</span>
          <span style="background:${{scoreColor(score)}};color:#fff;font-size:12px;font-weight:700;padding:2px 7px;border-radius:10px">Deal ${{score}}/100</span>
        </div>
        <div style="color:#555;font-size:12px;margin-top:3px">${{details}}</div>
        ${{pps ? `<div style="color:#888;font-size:11px;margin-top:2px">${{pps}}</div>` : ''}}
        ${{walkOk ? `
        <div style="margin-top:7px;padding-top:7px;border-top:1px solid #eee">
          <div style="color:#${{walkFar ? 'e65100' : '388e3c'}};font-size:12px;font-weight:600">🚶 ${{l.walk_min}} min walk to nearest stop</div>
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

  // Populate location dropdown
  const locs = [...new Set(LISTINGS.map(l => l.location).filter(Boolean))].sort();
  const locSel = document.getElementById('f-location');
  locs.forEach(loc => {{
    const opt = document.createElement('option');
    opt.value = opt.textContent = loc;
    locSel.appendChild(opt);
  }});
  locSel.size = Math.min(locs.length, 4);
  locSel.addEventListener('change', applyFilters);

  // Score chips: radio
  document.getElementById('f-score').addEventListener('click', e => {{
    if (!e.target.classList.contains('chip')) return;
    document.querySelectorAll('#f-score .chip').forEach(c => c.classList.remove('active'));
    e.target.classList.add('active');
    applyFilters();
  }});

  // Walk chips: radio
  document.getElementById('f-walk').addEventListener('click', e => {{
    if (!e.target.classList.contains('chip')) return;
    document.querySelectorAll('#f-walk .chip').forEach(c => c.classList.remove('active'));
    e.target.classList.add('active');
    applyFilters();
  }});

  document.getElementById('sort-select').addEventListener('change', applyFilters);
  applyFilters();
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

    with open("land_map.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved land_map.html ({len(with_coords)} markers)")


if __name__ == "__main__":
    with open("land_listings.json") as f:
        listings = json.load(f)
    make_land_map(listings)
