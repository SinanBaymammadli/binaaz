"""
Recalculates walking distance/time for houses_listings.json using OSRM
public routing API (real streets, foot profile).

For each listing: finds nearest 3 stops by straight-line, routes all 3
via OSRM, keeps whichever has the shortest real walking duration.
"""
import json
import math
import time
import urllib.request
import urllib.error

OSRM = "https://routing.openstreetmap.de/routed-foot/route/v1/foot/{lng1},{lat1};{lng2},{lat2}?overview=false"


def haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def osrm_walk(lat1, lng1, lat2, lng2, retries=3):
    url = OSRM.format(lat1=lat1, lng1=lng1, lat2=lat2, lng2=lng2)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.load(r)
            if data.get("code") == "Ok":
                route = data["routes"][0]
                return route["distance"], route["duration"]  # metres, seconds
            return None, None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                print(f"  OSRM error: {e}")
                return None, None


def build_stops():
    with open("ayna_stops.json") as f:
        raw = json.load(f)
    with open("all_buses.json") as f:
        buses = json.load(f)

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
            "id": sid, "lat": slat, "lng": slng,
            "name": info.get("name", f"stop#{sid}"),
            "lines": sorted(info.get("lines", [])),
        })
    return stops


def nearest_n(lat, lng, stops, n=3):
    dists = sorted(stops, key=lambda s: haversine(lat, lng, s["lat"], s["lng"]))
    return dists[:n]


def main():
    print("Building stop index...")
    stops = build_stops()
    print(f"  {len(stops)} valid stops")

    with open("houses_listings.json") as f:
        listings = json.load(f)

    total = len([l for l in listings if l.get("lat")])
    print(f"Routing {total} listings via OSRM (3 stops each)…")

    done = 0
    for l in listings:
        if not l.get("lat"):
            continue

        lat, lng = float(l["lat"]), float(l["lng"])
        candidates = nearest_n(lat, lng, stops, n=3)

        best_dur, best_dist, best_stop = float("inf"), None, None
        for s in candidates:
            dist_m, dur_s = osrm_walk(lat, lng, s["lat"], s["lng"])
            time.sleep(0.25)  # be polite to the public server
            if dur_s is not None and dur_s < best_dur:
                best_dur, best_dist, best_stop = dur_s, dist_m, s

        if best_stop:
            l["walk_m"] = round(best_dist)
            l["walk_min"] = round(best_dur / 60, 1)
            l["stop_name"] = best_stop["name"]
            l["bus_lines"] = best_stop["lines"]

        done += 1
        if done % 10 == 0 or done == total:
            print(f"  {done}/{total}")

    with open("houses_listings.json", "w") as f:
        json.dump(listings, f, ensure_ascii=False, indent=2)
    print("Saved houses_listings.json")

    # Quick sanity check
    sample = [l for l in listings if l.get("walk_min")][:5]
    for l in sample:
        print(f"  {l['id']}  {l['price']} AZN  {l['walk_min']} min walk  {l['bus_lines']}")


if __name__ == "__main__":
    main()
