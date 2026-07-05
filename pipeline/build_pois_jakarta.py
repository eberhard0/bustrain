#!/usr/bin/env python3
"""Jakarta landmarks from OSM -> web/data/jakarta/pois.json.

Sights, malls (a Jakarta institution), hotels, hospitals, universities and
airports. Restaurants are left to the live Photon fallback — central Jakarta
has tens of thousands and would bloat the offline index.
"""
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "jakarta" / "pois.json"
CACHE = ROOT / "data" / "raw" / "osm_pois_jakarta.json"

QUERY = """
[out:json][timeout:120];
(
  nwr["tourism"~"attraction|museum|aquarium|zoo|theme_park|viewpoint|gallery"]["name"](-6.35,106.68,-6.08,106.98);
  nwr["tourism"~"hotel|hostel|guest_house"]["name"](-6.32,106.72,-6.10,106.92);
  nwr["shop"="mall"]["name"](-6.35,106.68,-6.08,106.98);
  nwr["amenity"~"hospital|university"]["name"](-6.35,106.68,-6.08,106.98);
  nwr["aeroway"="aerodrome"]["name"](-6.35,106.60,-6.05,107.00);
  nwr["amenity"="place_of_worship"]["tourism"="attraction"]["name"](-6.35,106.68,-6.08,106.98);
);
out center tags;
"""

MANUAL = [
    ("Monumen Nasional (Monas)", "National Monument", -6.1754, 106.8272, "sight"),
    ("Kota Tua Jakarta", "Jakarta Old Town", -6.1352, 106.8133, "sight"),
    ("Masjid Istiqlal", "Istiqlal Mosque", -6.1699, 106.8309, "sight"),
    ("Taman Mini Indonesia Indah", "TMII", -6.3025, 106.8952, "sight"),
    ("Ancol Dreamland", "Taman Impian Jaya Ancol", -6.1226, 106.8306, "sight"),
    ("Kebun Binatang Ragunan", "Ragunan Zoo", -6.3124, 106.8201, "sight"),
    ("Grand Indonesia", "Grand Indonesia Mall", -6.1952, 106.8218, "mall"),
    ("Sarinah", "Sarinah Mall", -6.1870, 106.8241, "mall"),
    ("Gelora Bung Karno", "GBK Stadium", -6.2186, 106.8022, "sight"),
    ("Blok M", "Blok M district", -6.2444, 106.7986, "mall"),
    ("Bandara Soekarno-Hatta", "Soekarno-Hatta Airport (CGK)", -6.1256, 106.6559, "airport"),
    ("Bandara Halim Perdanakusuma", "Halim Airport (HLP)", -6.2666, 106.8909, "airport"),
]


def fetch():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    req = urllib.request.Request("https://overpass-api.de/api/interpreter",
                                 data=QUERY.encode(), headers={"User-Agent": "bustrain-builder"})
    data = json.loads(urllib.request.urlopen(req, timeout=180).read())
    CACHE.write_text(json.dumps(data), encoding="utf-8")
    time.sleep(1)
    return data


def kind_of(tags):
    if tags.get("aeroway"):
        return "airport"
    a = tags.get("amenity", "")
    if a == "hospital":
        return "hospital"
    if a == "university":
        return "university"
    if tags.get("tourism") in ("hotel", "hostel", "guest_house"):
        return "hotel"
    if tags.get("shop") == "mall":
        return "mall"
    if tags.get("tourism") == "museum":
        return "museum"
    return "sight"


def main():
    data = fetch()
    pois, seen = [], set()
    for e in data["elements"]:
        t = e.get("tags", {})
        name = t.get("name")
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")
        if not name or lat is None:
            continue
        key = (name, round(lat * 400), round(lon * 400))
        if key in seen:
            continue
        seen.add(key)
        pois.append({"n": name, "e": t.get("name:en", ""), "lat": round(lat, 5),
                     "lon": round(lon, 5), "k": kind_of(t)})
    for n, e_name, lat, lon, k in MANUAL:
        if not any(p["n"] == n for p in pois):
            pois.append({"n": n, "e": e_name, "lat": lat, "lon": lon, "k": k})
    OUT.write_text(json.dumps({"pois": pois}, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"jakarta: {len(pois)} POIs -> {OUT}")


if __name__ == "__main__":
    main()
