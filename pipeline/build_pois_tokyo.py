#!/usr/bin/env python3
"""Tokyo landmarks from OSM -> web/data/tokyo/pois.json.

Sights, museums, malls and airports in the central wards. Hotels and
restaurants are left to the live Photon fallback — central Tokyo has far too
many to bundle offline.
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "tokyo" / "pois.json"
CACHE = ROOT / "data" / "raw" / "osm_pois_tokyo.json"

QUERY = """
[out:json][timeout:120];
(
  nwr["tourism"~"attraction|museum|aquarium|zoo|theme_park|viewpoint|gallery"]["name"](35.58,139.60,35.78,139.92);
  nwr["shop"="mall"]["name"](35.58,139.60,35.78,139.92);
  nwr["amenity"~"hospital|university"]["name"](35.60,139.62,35.76,139.90);
  nwr["aeroway"="aerodrome"]["name"](35.52,139.72,35.58,139.82);
);
out center tags;
"""

MANUAL = [
    ("浅草寺", "Sensō-ji Temple (Asakusa)", 35.7148, 139.7967, "sight"),
    ("東京スカイツリー", "Tokyo Skytree", 35.7101, 139.8107, "sight"),
    ("東京タワー", "Tokyo Tower", 35.6586, 139.7454, "sight"),
    ("明治神宮", "Meiji Shrine", 35.6764, 139.6993, "sight"),
    ("渋谷スクランブル交差点", "Shibuya Crossing", 35.6595, 139.7005, "sight"),
    ("皇居", "Imperial Palace", 35.6852, 139.7528, "sight"),
    ("上野動物園", "Ueno Zoo", 35.7163, 139.7714, "sight"),
    ("築地場外市場", "Tsukiji Outer Market", 35.6654, 139.7707, "sight"),
    ("秋葉原電気街", "Akihabara Electric Town", 35.7022, 139.7741, "sight"),
    ("東京国立博物館", "Tokyo National Museum", 35.7188, 139.7765, "museum"),
    ("豊洲市場", "Toyosu Market", 35.6423, 139.7853, "sight"),
    ("お台場", "Odaiba", 35.6300, 139.7773, "sight"),
    ("新宿御苑", "Shinjuku Gyoen Garden", 35.6852, 139.7100, "sight"),
    ("羽田空港", "Haneda Airport (HND)", 35.5494, 139.7798, "airport"),
    ("成田空港", "Narita Airport (NRT)", 35.7720, 140.3929, "airport"),
]


def fetch():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    req = urllib.request.Request("https://overpass.kumi.systems/api/interpreter",
                                 data=("data=" + urllib.parse.quote(QUERY)).encode(),
                                 headers={"User-Agent": "bustrain-builder"})
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
    print(f"tokyo: {len(pois)} POIs -> {OUT}")


if __name__ == "__main__":
    main()
