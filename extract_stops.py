import osmium
import json
import csv

class BusStopHandler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.stops = []

    def node(self, n):
        tags = dict(n.tags)
        is_stop = (
            tags.get("highway") == "bus_stop"
            or tags.get("amenity") == "bus_station"
            or tags.get("public_transport") in ("stop_position", "platform")
            or tags.get("railway") in ("subway_entrance", "tram_stop", "halt", "station")
        )
        if is_stop:
            self.stops.append({
                "id": n.id,
                "lat": n.location.lat,
                "lng": n.location.lon,
                "name": tags.get("name") or tags.get("name:az") or tags.get("ref") or "",
                "name_en": tags.get("name:en", ""),
                "type": (
                    tags.get("highway")
                    or tags.get("amenity")
                    or tags.get("public_transport")
                    or tags.get("railway")
                    or "stop"
                ),
                "routes": tags.get("route_ref", ""),
            })

handler = BusStopHandler()
handler.apply_file("azerbaijan-latest.osm.pbf", locations=True)

print(f"Extracted {len(handler.stops)} transit stops")

# Save as JSON
with open("bus_stops.json", "w", encoding="utf-8") as f:
    json.dump(handler.stops, f, ensure_ascii=False, indent=2)

# Save as CSV
with open("bus_stops.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["id", "lat", "lng", "name", "name_en", "type", "routes"])
    writer.writeheader()
    writer.writerows(handler.stops)

print("Saved to bus_stops.json and bus_stops.csv")

# Quick breakdown by type
from collections import Counter
types = Counter(s["type"] for s in handler.stops)
for t, count in types.most_common():
    print(f"  {t}: {count}")
