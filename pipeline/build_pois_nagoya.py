#!/usr/bin/env python3
"""Nagoya landmarks from OSM -> web/data/nagoya/pois.json."""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "nagoya" / "pois.json"
CACHE = ROOT / "data" / "raw" / "osm_pois_nagoya.json"

QUERY = """
[out:json][timeout:120];
(
  nwr["tourism"~"attraction|museum|aquarium|zoo|theme_park|viewpoint|gallery"]["name"](35.03,136.78,35.28,137.05);
  nwr["shop"="mall"]["name"](35.03,136.78,35.28,137.05);
  nwr["amenity"~"hospital|university"]["name"](35.05,136.80,35.25,137.02);
  nwr["tourism"~"hotel|hostel|guest_house"]["name"](35.10,136.85,35.20,136.95);
);
out center tags;
"""

MANUAL = [
    ("名古屋城", "Nagoya Castle", 35.1856, 136.8998, "sight"),
    ("熱田神宮", "Atsuta Shrine", 35.1278, 136.9086, "sight"),
    ("大須商店街", "Ōsu Shopping District", 35.1595, 136.9028, "sight"),
    ("オアシス21", "Oasis 21 (Sakae)", 35.1707, 136.9105, "sight"),
    ("名古屋テレビ塔", "Chubu Electric MIRAI TOWER", 35.1720, 136.9084, "sight"),
    ("名古屋港水族館", "Port of Nagoya Aquarium", 35.0906, 136.8785, "sight"),
    ("トヨタ産業技術記念館", "Toyota Commemorative Museum", 35.1822, 136.8763, "museum"),
    ("リニア・鉄道館", "SCMAGLEV and Railway Park", 35.0399, 136.8434, "museum"),
    ("レゴランド・ジャパン", "LEGOLAND Japan", 35.0432, 136.8496, "sight"),
    ("徳川園", "Tokugawa Garden", 35.1849, 136.9333, "sight"),
    ("名古屋市科学館", "Nagoya City Science Museum", 35.1650, 136.8998, "museum"),
    ("中部国際空港", "Chubu Centrair Airport (NGO)", 34.8584, 136.8054, "airport"),
]


def fetch():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    req = urllib.request.Request("https://overpass-api.de/api/interpreter",
                                 data=("data=" + urllib.parse.quote(QUERY)).encode(),
                                 headers={"User-Agent": "bustrain-builder"})
    data = json.loads(urllib.request.urlopen(req, timeout=180).read())
    CACHE.write_text(json.dumps(data), encoding="utf-8")
    time.sleep(1)
    return data


def kind_of(tags):
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
        hit = next((p for p in pois if p["n"] == n), None)
        if hit:
            if not hit["e"]:
                hit["e"] = e_name
        else:
            pois.append({"n": n, "e": e_name, "lat": lat, "lon": lon, "k": k})
    OUT.write_text(json.dumps({"pois": pois}, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"nagoya: {len(pois)} POIs -> {OUT}")


if __name__ == "__main__":
    main()
